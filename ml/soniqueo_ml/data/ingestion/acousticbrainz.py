"""AcousticBrainz low-level feature dumps -> audio features for catalogue recordings.

The CSVs hold one row per submission (a recording can have several, `submission_offset` 0, 1, ...).
We keep the first submission. Mapping onto track_features columns:

- tempo        <- rhythm.bpm (beats per minute)
- danceability <- rhythm.danceability / 3, clipped to [0, 1] (Essentia's detrended-fluctuation
                  danceability is roughly 0-3)
- onset_rate   <- rhythm.onset_rate (onsets per second)
- loudness     <- lowlevel.average_loudness (already 0-1)
"""

from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv

from soniqueo_ml.data.ingestion.archives import iter_members

FEATURE_VERSION = "acousticbrainz-lowlevel-2022-06-23"
PART_COLUMNS = {
    "rhythm": {"bpm": pa.float64(), "danceability": pa.float64(), "onset_rate": pa.float64()},
    "lowlevel": {"average_loudness": pa.float64()},
}
ESSENTIA_DANCEABILITY_MAX = 3.0


def read_part(path: Path, part: str, mbids: pa.Array) -> pa.Table:
    """Stream one feature CSV and keep the first submission of each wanted recording."""
    columns = PART_COLUMNS[part]
    types = {"mbid": pa.string(), "submission_offset": pa.int32(), **columns}
    value_set = pc.unique(mbids)
    kept: list[pa.Table] = []
    for name, handle in iter_members(path):
        if not name.endswith(".csv"):
            continue
        reader = pcsv.open_csv(
            handle,
            read_options=pcsv.ReadOptions(block_size=64 << 20),
            convert_options=pcsv.ConvertOptions(include_columns=list(types), column_types=types),
        )
        for batch in reader:
            mask = pc.and_(
                pc.is_in(batch.column("mbid"), value_set=value_set),
                pc.equal(batch.column("submission_offset"), 0),
            )
            if pc.any(mask).as_py():
                kept.append(pa.Table.from_batches([batch]).filter(mask))
    schema = pa.schema([(key, value) for key, value in types.items()])
    table = pa.concat_tables(kept) if kept else schema.empty_table()
    return table.drop_columns(["submission_offset"])


def combine_features(rhythm: pa.Table, lowlevel: pa.Table) -> list[dict[str, float | str | None]]:
    """Join the parts and map them onto track_features columns."""
    joined = rhythm.join(lowlevel, "mbid", join_type="full outer")
    records = []
    for row in joined.to_pylist():
        tempo = row.get("bpm")
        dance = row.get("danceability")
        loudness = row.get("average_loudness")
        records.append(
            {
                "mbid": row["mbid"],
                "tempo": tempo if tempo is not None and 20 <= tempo <= 300 else None,
                "danceability": None
                if dance is None
                else min(1.0, max(0.0, dance / ESSENTIA_DANCEABILITY_MAX)),
                "onset_rate": row.get("onset_rate") if (row.get("onset_rate") or 0) >= 0 else None,
                "loudness": loudness if loudness is not None and 0 <= loudness <= 1 else None,
            }
        )
    return records
