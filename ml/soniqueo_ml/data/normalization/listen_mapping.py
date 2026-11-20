"""Link listens to MusicBrainz recordings and measure recording popularity.

Mapping order per listen:
1. The artist + title key matches the canonical dump ("canonical_text").
2. Otherwise, a recording MBID the listening client submitted itself ("client_mbid"). These are
   unvalidated, so they are only used when the text gives no answer.
"""

from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from soniqueo_ml.data.normalization.keys import track_matching_key

MAPPED_SCHEMA = pa.schema(
    [
        ("user_key", pa.string()),
        ("listened_at", pa.timestamp("s", tz="UTC")),
        ("recording_mbid", pa.string()),
        ("match_method", pa.string()),
    ]
)


def listen_files(listens_dir: Path) -> list[Path]:
    return sorted(listens_dir.glob("*.parquet"))


def unique_listen_keys(listens_dir: Path) -> pa.Array:
    """Distinct artist + title keys across all listens (computed on distinct pairs for speed)."""
    keys: list[pa.Array] = []
    for path in listen_files(listens_dir):
        pairs = (
            pq.read_table(path, columns=["artist_name", "track_name"])
            .group_by(["artist_name", "track_name"])
            .aggregate([])
        )
        keys.append(pc.unique(track_matching_key(pairs["artist_name"], pairs["track_name"])))
    return pc.unique(pa.chunked_array(keys, pa.string()))


def map_listens(listens_path: Path, mapping: pa.Table, out_path: Path) -> dict[str, int]:
    listens = pq.read_table(
        listens_path,
        columns=["user_key", "listened_at", "artist_name", "track_name", "client_recording_mbid"],
    )
    keyed = listens.append_column("key", track_matching_key(listens["artist_name"], listens["track_name"]))
    joined = keyed.join(mapping.select(["key", "recording_mbid"]), "key", join_type="left outer")
    by_text = joined["recording_mbid"]
    by_client = joined["client_recording_mbid"]
    recording = pc.coalesce(by_text, by_client)
    method = pc.if_else(
        pc.is_valid(by_text),
        pa.scalar("canonical_text"),
        pc.if_else(pc.is_valid(by_client), pa.scalar("client_mbid"), pa.scalar(None, pa.string())),
    )
    mapped = pa.table(
        {
            "user_key": joined["user_key"],
            "listened_at": joined["listened_at"],
            "recording_mbid": recording,
            "match_method": method,
        },
        schema=MAPPED_SCHEMA,
    )
    resolved = mapped.filter(pc.is_valid(mapped["recording_mbid"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(resolved, out_path, compression="zstd")
    counts = pc.value_counts(method).to_pylist()
    stats = {str(entry["values"]): int(entry["counts"]) for entry in counts}
    stats["total"] = listens.num_rows
    return stats


def mapped_listens(mapped_dir: Path) -> ds.Dataset:
    return ds.dataset(mapped_dir, format="parquet", schema=MAPPED_SCHEMA)


def recording_popularity(mapped_dir: Path) -> pa.Table:
    """Listeners and listens per recording, most-listened first. Duplicate listens are dropped."""
    table = mapped_listens(mapped_dir).to_table()
    unique = table.group_by(["user_key", "listened_at", "recording_mbid"]).aggregate([])
    listeners = unique.group_by("recording_mbid").aggregate(
        [("user_key", "count_distinct"), ("listened_at", "count")]
    )
    listeners = listeners.rename_columns(
        {"user_key_count_distinct": "listeners", "listened_at_count": "listens"}
    ).select(["recording_mbid", "listeners", "listens"])
    return listeners.sort_by(
        [("listeners", "descending"), ("listens", "descending")]
    )
