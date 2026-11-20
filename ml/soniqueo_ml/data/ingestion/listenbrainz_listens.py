"""ListenBrainz incremental listen dumps -> validated, pseudonymized listens (Parquet).

Privacy: the dumps are CC0 public data, but user names identify people, so they are replaced with
a keyed hash (HMAC-SHA256 with a secret, non-committed key) before anything is written. Raw names
never leave this module.

Each dump holds listens *submitted* during one day. Bulk imports of old history are dropped by
keeping only listens whose own timestamp falls inside the overall dump window, so the dataset
reflects real, time-ordered listening for time-aware evaluation.
"""

import hashlib
import hmac
import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.domains.catalogue.normalization import normalize_duration_ms
from soniqueo_ml.data.ingestion.archives import iter_members

LISTEN_SCHEMA = pa.schema(
    [
        ("user_key", pa.string()),
        ("listened_at", pa.timestamp("s", tz="UTC")),
        ("artist_name", pa.string()),
        ("track_name", pa.string()),
        ("release_name", pa.string()),
        ("duration_ms", pa.int32()),
        ("client_recording_mbid", pa.string()),
    ]
)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CHUNK_ROWS = 500_000


@dataclass(frozen=True)
class DumpWindow:
    start: datetime
    end: datetime


@dataclass
class ExtractStats:
    lines: int = 0
    kept: int = 0
    dropped: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {"lines": self.lines, "kept": self.kept, "dropped": dict(self.dropped)}


def _parse_timestamp(text: str) -> datetime:
    return datetime.fromisoformat(text.strip()).astimezone(UTC)


def read_window(path: Path) -> DumpWindow:
    """The submission window recorded in the dump's START/END_TIMESTAMP members."""
    values: dict[str, datetime] = {}
    for name, handle in iter_members(path):
        base = name.rsplit("/", 1)[-1]
        if base in ("START_TIMESTAMP", "END_TIMESTAMP"):
            values[base] = _parse_timestamp(handle.read().decode())
        if len(values) == 2 or name.endswith(".listens"):
            break
    return DumpWindow(values["START_TIMESTAMP"], values["END_TIMESTAMP"])


class Pseudonymizer:
    def __init__(self, key: bytes) -> None:
        if len(key) < 16:
            raise ValueError("pseudonymization key must be at least 16 bytes")
        self._key = key
        self._cache: dict[str, str] = {}

    def __call__(self, user_name: str) -> str:
        cached = self._cache.get(user_name)
        if cached is None:
            digest = hmac.new(self._key, user_name.encode(), hashlib.sha256).hexdigest()
            cached = self._cache[user_name] = digest[:20]
        return cached


def _duration_ms(info: dict[str, Any]) -> int | None:
    for key, scale in (("duration_ms", 1), ("duration", 1000)):
        value = info.get(key)
        if value is None:
            continue
        try:
            return normalize_duration_ms(float(value) * scale)
        except (TypeError, ValueError):
            return None
    return None


def parse_listen(
    raw: dict[str, Any], window: DumpWindow, pseudonymize: Pseudonymizer
) -> tuple[str, tuple[Any, ...] | None]:
    """Validate one dump line. Returns ("ok", row) or (rejection reason, None)."""
    user_name = raw.get("user_name")
    timestamp = raw.get("timestamp")
    metadata = raw.get("track_metadata") or {}
    artist = (metadata.get("artist_name") or "").strip()
    track = (metadata.get("track_name") or "").strip()
    if not isinstance(user_name, str) or not user_name:
        return "missing_user", None
    if not isinstance(timestamp, int):
        return "invalid_timestamp", None
    if not artist or not track:
        return "missing_artist_or_track", None
    listened_at = datetime.fromtimestamp(timestamp, UTC)
    if not window.start <= listened_at <= window.end:
        return "outside_window", None
    info = metadata.get("additional_info") or {}
    mbid = info.get("recording_mbid")
    mbid = mbid.lower() if isinstance(mbid, str) and _UUID.match(mbid.lower()) else None
    release = (metadata.get("release_name") or "").strip() or None
    return "ok", (pseudonymize(user_name), listened_at, artist, track, release, _duration_ms(info), mbid)


def iter_listen_lines(path: Path) -> Iterator[bytes]:
    for name, handle in iter_members(path):
        if name.endswith(".listens"):
            yield from handle


def _to_table(rows: list[tuple[Any, ...]]) -> pa.Table:
    columns: list[Sequence[Any]] = (
        list(zip(*rows, strict=True)) if rows else [[] for _ in LISTEN_SCHEMA]
    )
    return pa.Table.from_arrays(
        [pa.array(col, type=f.type) for col, f in zip(columns, LISTEN_SCHEMA, strict=True)],
        schema=LISTEN_SCHEMA,
    )


def extract_listens(
    lines: Iterable[bytes], window: DumpWindow, key: bytes, out_path: Path
) -> ExtractStats:
    """Validate and pseudonymize listens, writing them to `out_path` in chunks."""
    stats = ExtractStats()
    pseudonymize = Pseudonymizer(key)
    partial = out_path.with_suffix(".parquet.part")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[Any, ...]] = []
    with pq.ParquetWriter(partial, LISTEN_SCHEMA, compression="zstd") as writer:
        for line in lines:
            stats.lines += 1
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                stats.dropped["malformed_json"] += 1
                continue
            status, row = parse_listen(raw, window, pseudonymize)
            if row is None:
                stats.dropped[status] += 1
                continue
            rows.append(row)
            if len(rows) >= CHUNK_ROWS:
                writer.write_table(_to_table(rows))
                stats.kept += len(rows)
                rows = []
        writer.write_table(_to_table(rows))
        stats.kept += len(rows)
    partial.replace(out_path)
    return stats


def extract_dump(path: Path, window: DumpWindow, key: bytes, out_dir: Path) -> dict[str, Any]:
    """Process one dump file (run in a worker process)."""
    out_path = out_dir / (path.name.removesuffix(".tar.zst") + ".parquet")
    stats = extract_listens(iter_listen_lines(path), window, key, out_path)
    return {"file": path.name, **stats.as_dict()}
