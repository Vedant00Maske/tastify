from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from soniqueo_ml.data.ingestion.listenbrainz_listens import LISTEN_SCHEMA
from soniqueo_ml.data.ingestion.musicbrainz_canonical import (
    build_key_mapping,
    iter_canonical_batches,
)
from soniqueo_ml.data.normalization.listen_mapping import (
    map_listens,
    recording_popularity,
    unique_listen_keys,
)
from tests.conftest import write_tar_zst

CANONICAL_HEADER = (
    b"id,artist_credit_id,artist_mbids,artist_credit_name,release_mbid,release_name,"
    b"recording_mbid,recording_name,combined_lookup,score" + bytes([10])
)
CANONICAL_CSV = (
    CANONICAL_HEADER
    + b"""1,10,a1,Mitski,rel-2,Laurel Hell (Deluxe),rec-guess,I Guess,x,20
2,10,a1,Mitski,rel-1,Laurel Hell,rec-guess,I Guess,x,5
3,11,a2,Bj\xc3\xb6rk,rel-3,Homogenic,rec-joga,J\xc3\xb3ga,x,7
4,11,a2,Bj\xc3\xb6rk,rel-4,Live,rec-joga-live,J\xc3\xb3ga,x,9
5,12,a3,Nobody Listens,rel-5,Nothing,rec-unheard,Silence,x,1
"""
)
T0 = datetime(2026, 11, 15, 12, tzinfo=UTC)


def write_listens(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    full = [
        {"release_name": None, "duration_ms": None, "client_recording_mbid": None, **row}
        for row in rows
    ]
    pq.write_table(pa.Table.from_pylist(full, schema=LISTEN_SCHEMA), path)
    return path


def canonical_dump(tmp_path: Path) -> Path:
    return write_tar_zst(
        tmp_path / "canonical.tar.zst",
        {
            "dump/TIMESTAMP": b"2026-11-03",
            "dump/canonical/canonical_musicbrainz_data.csv": CANONICAL_CSV,
        },
    )


def test_mapping_keeps_wanted_keys_and_prefers_the_lowest_score(tmp_path: Path) -> None:
    wanted = pa.array(["mitski|iguess", "bjork|joga", "someone|unknown"])

    mapping = build_key_mapping(iter_canonical_batches(canonical_dump(tmp_path)), wanted)

    rows = {row["key"]: row for row in mapping.to_pylist()}
    assert set(rows) == {"mitski|iguess", "bjork|joga"}
    assert rows["mitski|iguess"]["recording_mbid"] == "rec-guess"
    assert rows["mitski|iguess"]["release_mbid"] == "rel-1"  # score 5 beats 20
    assert rows["mitski|iguess"]["candidate_recordings"] == 1
    assert rows["bjork|joga"]["recording_mbid"] == "rec-joga"
    assert rows["bjork|joga"]["candidate_recordings"] == 2  # studio and live share the text


def test_listens_map_by_text_then_fall_back_to_client_mbids(tmp_path: Path) -> None:
    listens = write_listens(
        tmp_path / "listens" / "day1.parquet",
        [
            {"user_key": "u1", "listened_at": T0, "artist_name": "MITSKI", "track_name": "I Guess"},
            {"user_key": "u2", "listened_at": T0, "artist_name": "Bjork", "track_name": "Joga!"},
            {
                "user_key": "u2",
                "listened_at": T0,
                "artist_name": "Obscure",
                "track_name": "Demo",
                "client_recording_mbid": "rec-client",
            },
            {"user_key": "u3", "listened_at": T0, "artist_name": "Unknown", "track_name": "Track"},
        ],
    )
    keys = unique_listen_keys(listens.parent)
    mapping = build_key_mapping(iter_canonical_batches(canonical_dump(tmp_path)), keys)

    stats = map_listens(listens, mapping, tmp_path / "mapped" / "day1.parquet")

    mapped = pq.read_table(tmp_path / "mapped" / "day1.parquet").to_pylist()
    assert stats == {"canonical_text": 2, "client_mbid": 1, "None": 1, "total": 4}
    assert {(m["user_key"], m["recording_mbid"], m["match_method"]) for m in mapped} == {
        ("u1", "rec-guess", "canonical_text"),
        ("u2", "rec-joga", "canonical_text"),
        ("u2", "rec-client", "client_mbid"),
    }


def test_popularity_counts_distinct_listeners_and_ignores_duplicate_listens(tmp_path: Path) -> None:
    mapped = tmp_path / "mapped"
    mapped.mkdir()
    rows = [
        ("u1", T0, "rec-a"),
        ("u1", T0, "rec-a"),  # the same listen submitted twice
        ("u1", T0.replace(hour=13), "rec-a"),
        ("u2", T0, "rec-a"),
        ("u3", T0, "rec-b"),
    ]
    pq.write_table(
        pa.table(
            {
                "user_key": [r[0] for r in rows],
                "listened_at": pa.array([r[1] for r in rows], pa.timestamp("s", tz="UTC")),
                "recording_mbid": [r[2] for r in rows],
                "match_method": ["canonical_text"] * len(rows),
            }
        ),
        mapped / "day1.parquet",
    )

    popularity = recording_popularity(mapped).to_pylist()

    assert popularity == [
        {"recording_mbid": "rec-a", "listeners": 2, "listens": 3},
        {"recording_mbid": "rec-b", "listeners": 1, "listens": 1},
    ]
