import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from tastify_ml.data.ingestion.listenbrainz_listens import (
    DumpWindow,
    Pseudonymizer,
    extract_dump,
    read_window,
)
from tests.conftest import write_tar_zst

KEY = b"0123456789abcdef-test-key"
START = datetime(2026, 11, 15, tzinfo=UTC)
END = datetime(2026, 11, 16, tzinfo=UTC)
NOON = int(datetime(2026, 11, 15, 12, tzinfo=UTC).timestamp())


def listen(**overrides: object) -> bytes:
    record: dict[str, object] = {
        "user_id": 1,
        "user_name": "alice",
        "timestamp": NOON,
        "track_metadata": {
            "artist_name": "Mitski",
            "track_name": "I Guess",
            "release_name": "Laurel Hell",
            "additional_info": {
                "duration_ms": 135171,
                "recording_mbid": "9C4D04A6-B97D-46C8-BC49-2A3090737078",
            },
        },
        "recording_msid": "9c4d04a6-b97d-46c8-bc49-2a3090737078",
    }
    record.update(overrides)
    return json.dumps(record).encode()


@pytest.fixture
def dump(tmp_path: Path) -> Path:
    lines = [
        listen(),
        listen(user_name="bob", track_metadata={"artist_name": "Björk", "track_name": "Jóga"}),
        listen(timestamp=int(datetime(2015, 1, 1, tzinfo=UTC).timestamp())),  # imported history
        listen(track_metadata={"artist_name": "", "track_name": "No Artist"}),
        listen(timestamp="yesterday"),
        b"{not json",
    ]
    return write_tar_zst(
        tmp_path / "listenbrainz-listens-dump-1-incremental.tar.zst",
        {
            "dump/START_TIMESTAMP": b"2026-11-15 00:00:03.080727+00:00",
            "dump/END_TIMESTAMP": b"2026-11-16 00:00:03.031693+00:00",
            "dump/listens/2026/11.listens": b"\n".join(lines) + b"\n",
        },
    )


def test_read_window_uses_dump_timestamps(dump: Path) -> None:
    window = read_window(dump)

    assert window.start.isoformat().startswith("2026-11-15T00:00:03")
    assert window.end.isoformat().startswith("2026-11-16T00:00:03")


def test_extract_keeps_valid_listens_and_counts_rejections(dump: Path, tmp_path: Path) -> None:
    stats = extract_dump(dump, DumpWindow(START, END), KEY, tmp_path / "out")

    table = pq.read_table(tmp_path / "out" / "listenbrainz-listens-dump-1-incremental.parquet")
    assert stats["lines"] == 6
    assert stats["kept"] == 2
    assert stats["dropped"] == {
        "outside_window": 1,
        "missing_artist_or_track": 1,
        "invalid_timestamp": 1,
        "malformed_json": 1,
    }
    rows = table.to_pylist()
    assert rows[0]["artist_name"] == "Mitski"
    assert rows[0]["duration_ms"] == 135171
    assert rows[0]["client_recording_mbid"] == "9c4d04a6-b97d-46c8-bc49-2a3090737078"
    assert rows[1]["duration_ms"] is None
    assert rows[1]["client_recording_mbid"] is None


def test_user_names_never_reach_the_output(dump: Path, tmp_path: Path) -> None:
    extract_dump(dump, DumpWindow(START, END), KEY, tmp_path / "out")

    users = pq.read_table(tmp_path / "out").column("user_key").to_pylist()
    assert "alice" not in users
    assert "bob" not in users
    assert users[0] == Pseudonymizer(KEY)("alice")


def test_pseudonyms_are_stable_per_key_and_differ_across_keys() -> None:
    first, again = Pseudonymizer(KEY), Pseudonymizer(KEY)
    other = Pseudonymizer(b"another-secret-key-0000")

    assert first("alice") == again("alice")
    assert first("alice") != first("bob")
    assert first("alice") != other("alice")


def test_short_keys_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least 16 bytes"):
        Pseudonymizer(b"short")
