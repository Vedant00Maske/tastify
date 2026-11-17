"""API representations of playlists (API_SPEC.md)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domains.catalogue.schemas import TrackSummary
from app.domains.playlists.models import MAX_TRACKS

Collection = Literal["for_you", "mood", "hidden_gems", "genre", "artist_radio"]


class Generator(BaseModel):
    """How a generated playlist is (re)made. Fields depend on the collection."""

    collection: Collection
    mood: str | None = Field(default=None, max_length=64)
    genre: str | None = Field(default=None, max_length=100)
    artist_id: uuid.UUID | None = None
    size: int = Field(default=25, ge=5, le=100)

    @model_validator(mode="after")
    def _complete(self) -> "Generator":
        required = {"mood": self.mood, "genre": self.genre, "artist_radio": self.artist_id}
        if self.collection in required and required[self.collection] is None:
            field = "artist_id" if self.collection == "artist_radio" else self.collection
            raise ValueError(f"{self.collection} playlists need `{field}`")
        return self


def _name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("name must not be empty")
    return cleaned


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    track_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_TRACKS)
    generator: Generator | None = None

    @field_validator("name")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _name(value)


class PlaylistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return None if value is None else _name(value)


class TracksAdd(BaseModel):
    track_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_TRACKS)


class TracksOrder(BaseModel):
    track_ids: list[uuid.UUID] = Field(
        min_length=1, max_length=MAX_TRACKS, description="Every track of the playlist, in order."
    )


class PlaylistSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    kind: str
    collection: str | None
    track_count: int
    duration_ms: int | None = Field(description="Total, when every track's duration is known.")
    artwork_urls: list[str] = Field(description="Covers of the first tracks, for a collage.")
    created_at: datetime
    updated_at: datetime


class PlaylistTrackOut(TrackSummary):
    position: int
    added_at: datetime


class PlaylistDetail(PlaylistSummary):
    generator: dict[str, Any] | None
    tracks: list[PlaylistTrackOut]


class PlaylistList(BaseModel):
    playlists: list[PlaylistSummary]
