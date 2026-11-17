"""API representations of catalogue entities.

Provider-specific details appear only as identifiers, so clients never depend on one provider.
"""

import uuid

from pydantic import BaseModel, Field


class ExternalIdOut(BaseModel):
    provider: str
    external_id: str
    match_method: str
    confidence: float


class CreditOut(BaseModel):
    artist_id: uuid.UUID
    name: str
    join_phrase: str


class AlbumRef(BaseModel):
    id: uuid.UUID
    title: str
    album_type: str | None
    release_year: int | None


class GenreOut(BaseModel):
    name: str
    weight: float
    level: str
    source: str


class FeaturesOut(BaseModel):
    source: str
    version: str
    tempo: float | None
    energy: float | None
    danceability: float | None
    valence: float | None
    acousticness: float | None
    instrumentalness: float | None
    loudness: float | None
    onset_rate: float | None


class SourceOut(BaseModel):
    key: str
    license: str
    usage_restriction: str


class TrackSummary(BaseModel):
    id: uuid.UUID
    title: str
    artist: str
    """Display artist credit, e.g. "Jay-Z feat. Beyoncé"."""
    duration_ms: int | None
    release_year: int | None
    artist_id: uuid.UUID | None = None
    album_title: str | None = None
    artwork_url: str | None = Field(
        default=None,
        description="Album cover (Cover Art Archive); null when unknown or disabled.",
    )


class TrackDetail(TrackSummary):
    isrc: str | None
    credits: list[CreditOut]
    album: AlbumRef | None
    genres: list[GenreOut]
    features: list[FeaturesOut]
    external_ids: list[ExternalIdOut]
    sources: list[SourceOut]


class ArtistDetail(BaseModel):
    id: uuid.UUID
    name: str
    artist_type: str | None
    area: str | None
    begin_year: int | None
    genres: list[GenreOut]
    external_ids: list[ExternalIdOut]
    track_count: int


class TrackSearchResponse(BaseModel):
    query: str
    results: list[TrackSummary]


class ArtistSummary(BaseModel):
    id: uuid.UUID
    name: str
    area: str | None
    genres: list[str]
    track_count: int
    artwork_url: str | None = Field(
        default=None, description="Cover of one of the artist's albums, when known."
    )


class ArtistSearchResponse(BaseModel):
    query: str
    results: list[ArtistSummary]


class GenreSummary(BaseModel):
    name: str
    tracks: int


class GenreListResponse(BaseModel):
    genres: list[GenreSummary]
