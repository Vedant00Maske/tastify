"""Source-agnostic records that ingestion pipelines produce and the catalogue writer consumes.

Each source adapter (MusicBrainz, FMA, later Spotify/YouTube) parses its own format into these
models. Validation errors raised here are recorded as ingestion errors, not loaded.
"""

from pydantic import BaseModel, Field, field_validator

from app.domains.catalogue.normalization import (
    normalize_duration_ms,
    normalize_isrc,
)
from app.domains.catalogue.resolution import TrackEvidence


class SourceGenreTag(BaseModel):
    name: str = Field(min_length=1)
    musicbrainz_id: str | None = None
    count: int = Field(default=1, ge=1)


class SourceArtist(BaseModel):
    provider: str
    external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    artist_type: str | None = None
    area: str | None = None
    begin_year: int | None = Field(default=None, ge=1000, le=2100)
    genres: list[SourceGenreTag] = Field(default_factory=list)


class SourceCredit(BaseModel):
    artist: SourceArtist
    credited_name: str
    join_phrase: str = ""


class SourceAlbum(BaseModel):
    provider: str
    external_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    album_type: str | None = None
    release_date: str | None = None
    genres: list[SourceGenreTag] = Field(default_factory=list)


class SourceTrack(BaseModel):
    provider: str
    external_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    credits: list[SourceCredit] = Field(min_length=1)
    duration_ms: int | None = None
    isrcs: list[str] = Field(default_factory=list)
    album: SourceAlbum | None = None
    release_date: str | None = None
    genres: list[SourceGenreTag] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title is blank")
        return stripped

    @field_validator("duration_ms", mode="before")
    @classmethod
    def _plausible_duration(cls, value: float | int | None) -> int | None:
        return normalize_duration_ms(value)

    @field_validator("isrcs", mode="before")
    @classmethod
    def _valid_isrcs(cls, value: list[str] | None) -> list[str]:
        normalized = (normalize_isrc(isrc) for isrc in value or [])
        return sorted({isrc for isrc in normalized if isrc})

    @property
    def primary_artist(self) -> SourceArtist:
        return self.credits[0].artist

    def evidence(self) -> TrackEvidence:
        return TrackEvidence(
            title=self.title,
            artists=tuple(credit.credited_name or credit.artist.name for credit in self.credits),
            duration_ms=self.duration_ms,
            isrcs=frozenset(self.isrcs),
            album=self.album.title if self.album else None,
        )
