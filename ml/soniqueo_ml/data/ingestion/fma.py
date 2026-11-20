"""FMA research dataset (fma_metadata.zip) -> SourceTrack records and Echonest audio features.

Only tracks with Echonest features (about 13k of 106k) are ingested: they are what FMA adds to the
catalogue (audio features for content-based experiments). FMA has no ISRCs or MusicBrainz ids, so
cross-source links rely on the metadata rules of the resolution policy.
"""

import ast
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd

from app.domains.catalogue.ingestion import (
    SourceAlbum,
    SourceArtist,
    SourceCredit,
    SourceGenreTag,
    SourceTrack,
)

PROVIDER = "fma"
FEATURE_VERSION = "echonest-fma-2017"
ECHONEST_FEATURES = ("tempo", "energy", "danceability", "valence", "acousticness", "instrumentalness")


@dataclass(frozen=True)
class FmaGenre:
    genre_id: int
    title: str
    parent_id: int | None


def _member(archive: zipfile.ZipFile, name: str) -> str:
    return next(n for n in archive.namelist() if n.endswith(f"/{name}") or n == name)


def read_genres(archive: zipfile.ZipFile) -> list[FmaGenre]:
    with archive.open(_member(archive, "genres.csv")) as handle:
        frame = pd.read_csv(handle)
    return [
        FmaGenre(int(row["genre_id"]), str(row["title"]), int(row["parent"]) or None)
        for row in frame.to_dict("records")
    ]


def read_echonest(archive: zipfile.ZipFile) -> pd.DataFrame:
    """Echonest audio features indexed by FMA track id."""
    with archive.open(_member(archive, "echonest.csv")) as handle:
        frame = pd.read_csv(handle, index_col=0, header=[0, 1, 2])
    audio = cast(pd.DataFrame, frame["echonest", "audio_features"])
    return audio[list(ECHONEST_FEATURES)].astype(float)


FEATURE_RANGES = {"tempo": (20.0, 300.0)} | {
    name: (0.0, 1.0) for name in ECHONEST_FEATURES if name != "tempo"
}


def validate_features(values: Mapping[str, float]) -> tuple[dict[str, float | None], list[str]]:
    """Null out missing or out-of-range values (Echonest reports unknown tempo as 0).

    Returns the cleaned features and the names of the rejected ones.
    """
    cleaned: dict[str, float | None] = {}
    rejected: list[str] = []
    for name, (low, high) in FEATURE_RANGES.items():
        value = values.get(name)
        if value is None or pd.isna(value) or not low <= value <= high:
            cleaned[name] = None
            rejected.append(name)
        else:
            cleaned[name] = float(value)
    return cleaned, rejected


def echonest_by_track(echonest: pd.DataFrame) -> dict[int, dict[str, float]]:
    return {
        int(track_id): {str(name): float(value) for name, value in values.items()}
        for track_id, values in zip(echonest.index.tolist(), echonest.to_dict("records"), strict=True)
    }


def read_tracks(archive: zipfile.ZipFile, track_ids: pd.Index | None = None) -> pd.DataFrame:
    with archive.open(_member(archive, "tracks.csv")) as handle:
        frame = pd.read_csv(handle, index_col=0, header=[0, 1], low_memory=False)
    frame.columns = [".".join(map(str, column)) for column in frame.columns]
    return frame if track_ids is None else frame.loc[frame.index.intersection(track_ids)]


def _text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _year(value: Any) -> int | None:
    text = _text(value)
    if text and text[:4].isdigit():
        year = int(text[:4])
        return year if 1000 <= year <= 2100 else None
    return None


def parse_track(track_id: int, row: Mapping[str, Any], genres: dict[int, FmaGenre]) -> SourceTrack:
    """One tracks.csv row (as a dict) -> SourceTrack.

    Raises pydantic.ValidationError for unusable rows.
    """
    genre_ids = ast.literal_eval(_text(row.get("track.genres")) or "[]")
    album_id = row.get("album.id")
    artist = SourceArtist(
        provider=PROVIDER,
        external_id=str(int(row["artist.id"])),
        name=_text(row.get("artist.name")) or "",
        begin_year=_year(row.get("artist.active_year_begin")),
    )
    album_title = _text(row.get("album.title"))
    album = (
        SourceAlbum(
            provider=PROVIDER,
            external_id=str(int(row["album.id"])),
            title=album_title,
            album_type=_text(row.get("album.type")),
            release_date=(_text(row.get("album.date_released")) or "")[:10] or None,
        )
        if album_title and album_id is not None and not pd.isna(album_id)
        else None
    )
    duration = row.get("track.duration")
    return SourceTrack(
        provider=PROVIDER,
        external_id=str(track_id),
        title=_text(row.get("track.title")) or "",
        credits=[SourceCredit(artist=artist, credited_name=artist.name)],
        duration_ms=None if duration is None or pd.isna(duration) else float(duration) * 1000,
        album=album,
        genres=[SourceGenreTag(name=genres[g].title) for g in genre_ids if g in genres],
    )


def iter_rows(tracks: pd.DataFrame) -> list[tuple[int, dict[str, Any]]]:
    """(track id, row as dict) pairs, ready for parse_track."""
    records = ({str(k): v for k, v in record.items()} for record in tracks.to_dict("records"))
    return list(zip((int(i) for i in tracks.index.tolist()), records, strict=True))


def open_metadata(path: Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(path)
