"""ListenBrainz `/1/metadata/recording` payloads (MusicBrainz data) -> SourceTrack records.

Genres: MusicBrainz flags tags that are genres with a `genre_mbid`. Those, plus tags whose name
is in the MusicBrainz genre list, become genres; other tags ("2010s", "english") are ignored here.
"""

from typing import Any

from app.domains.catalogue.ingestion import (
    SourceAlbum,
    SourceArtist,
    SourceCredit,
    SourceGenreTag,
    SourceTrack,
)

PROVIDER = "musicbrainz"


def _tags(entries: list[dict[str, Any]] | None) -> list[SourceGenreTag]:
    tags = []
    for entry in entries or []:
        name = (entry.get("tag") or "").strip()
        if name:
            tags.append(
                SourceGenreTag(
                    name=name,
                    musicbrainz_id=entry.get("genre_mbid"),
                    count=max(1, int(entry.get("count") or 1)),
                )
            )
    return tags


def parse_recording(recording_mbid: str, payload: dict[str, Any]) -> SourceTrack:
    """Build a SourceTrack. Raises pydantic.ValidationError/KeyError for unusable payloads."""
    recording = payload["recording"]
    artist_block = payload.get("artist") or {}
    tag_block = payload.get("tag") or {}
    release = payload.get("release") or {}

    artist_tags: dict[str, list[dict[str, Any]]] = {}
    for entry in tag_block.get("artist") or []:
        artist_tags.setdefault(entry.get("artist_mbid", ""), []).append(entry)

    credits = [
        SourceCredit(
            artist=SourceArtist(
                provider=PROVIDER,
                external_id=artist["artist_mbid"],
                name=artist["name"],
                artist_type=artist.get("type"),
                area=artist.get("area"),
                begin_year=artist.get("begin_year"),
                genres=_tags(artist_tags.get(artist["artist_mbid"])),
            ),
            credited_name=artist.get("name", ""),
            join_phrase=artist.get("join_phrase") or "",
        )
        for artist in artist_block.get("artists") or []
    ]

    album = None
    if release.get("release_group_mbid") and release.get("name"):
        album = SourceAlbum(
            provider=PROVIDER,
            external_id=release["release_group_mbid"],
            title=release["name"],
            release_date=str(release["year"]) if release.get("year") else None,
            genres=_tags(tag_block.get("release_group")),
        )

    return SourceTrack(
        provider=PROVIDER,
        external_id=recording_mbid,
        title=recording.get("name") or "",
        credits=credits,
        duration_ms=recording.get("length"),
        isrcs=recording.get("isrcs") or [],
        album=album,
        release_date=recording.get("first_release_date"),
        genres=_tags(tag_block.get("recording")),
    )
