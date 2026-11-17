"""API representations of users, interactions, preferences and taste profiles (API_SPEC.md)."""

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domains.catalogue.schemas import TrackSummary
from app.domains.users.events import EventType
from app.domains.users.profile import ExplorationMode

MAX_BATCH = 500
# Clients may be slightly ahead of the server clock; anything further is rejected.
CLOCK_SKEW = timedelta(minutes=5)


class InteractionIn(BaseModel):
    track_id: uuid.UUID
    event_type: EventType
    occurred_at: datetime | None = Field(
        default=None, description="When it happened (UTC offset required). Defaults to now."
    )
    position_ms: int | None = Field(
        default=None, ge=0, le=86_400_000, description="Playback position, e.g. of a skip."
    )
    session_id: uuid.UUID | None = None
    client_event_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="Idempotency key: an event with an already recorded id is ignored.",
    )

    @field_validator("occurred_at")
    @classmethod
    def _aware_and_not_future(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("occurred_at needs a UTC offset")
        if value > datetime.now(UTC) + CLOCK_SKEW:
            raise ValueError("occurred_at is in the future")
        return value


class InteractionBatch(BaseModel):
    events: list[InteractionIn] = Field(min_length=1, max_length=MAX_BATCH)
    source: str = Field(default="app", max_length=32, pattern=r"^[a-z0-9_]+$")


class InteractionOut(BaseModel):
    id: uuid.UUID
    track_id: uuid.UUID
    event_type: EventType
    occurred_at: datetime
    received_at: datetime
    position_ms: int | None
    session_id: uuid.UUID | None
    source: str
    track: TrackSummary | None = None


class InteractionHistory(BaseModel):
    items: list[InteractionOut]
    next_before: datetime | None = Field(
        description="Pass as `before` to get the next (older) page; null on the last page."
    )


class PreferencesIn(BaseModel):
    exploration_mode: ExplorationMode | None = Field(
        default=None, description="null: derived from listening behaviour."
    )
    personalization_enabled: bool = True
    preferred_artists: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    excluded_artists: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    preferred_genres: list[str] = Field(default_factory=list, max_length=30)
    excluded_genres: list[str] = Field(default_factory=list, max_length=50)
    preferred_moods: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("preferred_genres", "excluded_genres")
    @classmethod
    def _genre_names(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip() for v in values]
        if any(not v or len(v) > 100 for v in cleaned):
            raise ValueError("genre names must be 1-100 characters")
        return cleaned

    @model_validator(mode="after")
    def _no_conflicts(self) -> "PreferencesIn":
        if set(self.preferred_artists) & set(self.excluded_artists):
            raise ValueError("an artist cannot be both preferred and excluded")
        preferred = {g.lower() for g in self.preferred_genres}
        if preferred & {g.lower() for g in self.excluded_genres}:
            raise ValueError("a genre cannot be both preferred and excluded")
        return self


class ArtistRef(BaseModel):
    artist_id: uuid.UUID
    name: str


class PreferencesOut(BaseModel):
    exploration_mode: ExplorationMode | None
    personalization_enabled: bool
    preferred_artists: list[ArtistRef]
    excluded_artists: list[ArtistRef]
    preferred_genres: list[str]
    excluded_genres: list[str]
    preferred_moods: list[str]
    updated_at: datetime | None


class ArtistAffinityOut(BaseModel):
    artist_id: uuid.UUID
    name: str
    score: float


class GenreAffinityOut(BaseModel):
    genre: str
    score: float


class TasteProfileOut(BaseModel):
    """The user's taste profile (spec §8.4): what TASTIFY learned, and why it recommends."""

    user_id: uuid.UUID
    profile_version: str
    content_model_version: str | None
    updated_at: datetime
    as_of: datetime
    genre_affinity: list[GenreAffinityOut]
    artist_affinity: list[ArtistAffinityOut]
    negative_artists: list[ArtistAffinityOut]
    listening_frequency: dict[str, float]
    exploration_preference: float = Field(
        description="Behaviour-derived share of listening spread over different artists."
    )
    exploration_mode: ExplorationMode | None
    discovery_target: float = Field(
        description="Share of new-artist tracks the personalized mix aims for."
    )
    history_size: int
    interaction_count: int
    last_event_at: datetime | None
    long_term_embedding: list[float] | None = None
    short_term_embedding: list[float] | None = None


class InteractionsRecorded(BaseModel):
    recorded: int
    duplicates: int
    profile: TasteProfileOut


class FeedbackState(BaseModel):
    liked: bool
    disliked: bool
    saved: bool


class FeedbackStates(BaseModel):
    """Current like/dislike/save state per requested track (latest event wins)."""

    states: dict[uuid.UUID, FeedbackState]
