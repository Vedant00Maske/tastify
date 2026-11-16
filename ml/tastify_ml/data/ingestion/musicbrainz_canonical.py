"""MusicBrainz canonical data dump -> (artist + title key) -> canonical recording MBID.

The dump's canonical_musicbrainz_data.csv lists, for every canonical recording, each release it
appears on with its artist credit and title, ranked by `score` (lower = the release MusicBrainz
considers most canonical). This is the data ListenBrainz itself uses to link listens to recordings.
We stream the CSV (several GB) and keep only rows whose key occurs in our listens.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import IO

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv

from tastify_ml.data.ingestion.archives import iter_members
from tastify_ml.data.normalization.keys import track_matching_key

DATA_MEMBER = "canonical_musicbrainz_data.csv"
COLUMNS = ("artist_credit_name", "artist_mbids", "release_mbid", "recording_mbid", "recording_name", "score")
MAPPING_SCHEMA = pa.schema(
    [
        ("key", pa.string()),
        ("recording_mbid", pa.string()),
        ("artist_mbids", pa.string()),
        ("release_mbid", pa.string()),
        ("candidate_recordings", pa.int64()),
    ]
)


def iter_csv_batches(handle: IO[bytes], block_size: int = 64 << 20) -> Iterator[pa.RecordBatch]:
    reader = pcsv.open_csv(
        handle,
        read_options=pcsv.ReadOptions(block_size=block_size),
        parse_options=pcsv.ParseOptions(newlines_in_values=True),
        convert_options=pcsv.ConvertOptions(
            include_columns=list(COLUMNS),
            column_types={name: pa.string() for name in COLUMNS if name != "score"}
            | {"score": pa.int64()},
        ),
    )
    yield from reader


def iter_canonical_batches(path: Path) -> Iterator[pa.RecordBatch]:
    for name, handle in iter_members(path):
        if name.endswith(DATA_MEMBER):
            yield from iter_csv_batches(handle)
            return
    raise FileNotFoundError(f"{DATA_MEMBER} not found in {path.name}")


def build_key_mapping(batches: Iterator[pa.RecordBatch], wanted_keys: pa.Array) -> pa.Table:
    """Best (lowest-score) canonical recording for each wanted key.

    `candidate_recordings` counts distinct recordings sharing the key: values above 1 mean the
    text is ambiguous (e.g. a song re-recorded by the same artist) and the choice is less certain.
    """
    value_set = pc.unique(wanted_keys)
    kept: list[pa.Table] = []
    for batch in batches:
        keys = track_matching_key(batch.column("artist_credit_name"), batch.column("recording_name"))
        mask = pc.is_in(keys, value_set=value_set)
        if pc.any(mask).as_py():
            selected = pa.Table.from_batches([batch]).filter(mask)
            kept.append(selected.append_column("key", keys.filter(mask)))
    if not kept:
        return MAPPING_SCHEMA.empty_table()
    rows = pa.concat_tables(kept)
    candidates = rows.group_by("key").aggregate([("recording_mbid", "count_distinct")])
    best = rows.sort_by([("key", "ascending"), ("score", "ascending")])
    first_index = (
        best.append_column("row", pa.array(range(best.num_rows), pa.int64()))
        .group_by("key")
        .aggregate([("row", "min")])
        .column("row_min")
    )
    chosen = best.take(first_index).select(["key", "recording_mbid", "artist_mbids", "release_mbid"])
    mapping = chosen.join(candidates, "key")
    mapping = mapping.rename_columns(
        {"recording_mbid_count_distinct": "candidate_recordings"}
    )
    return mapping.select(MAPPING_SCHEMA.names).cast(MAPPING_SCHEMA)
