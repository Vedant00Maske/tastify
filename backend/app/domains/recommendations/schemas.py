"""API representations of recommendations (API_SPEC.md, "Example Recommendation Request")."""

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class Strategy(StrEnum):
    SIMILAR_TRACKS = "similar_tracks"
    SIMILAR_ARTISTS = "similar_artists"
    GENRE = "genre"
    POPULAR = "popular"
    TRENDING = "trending"
    # Milestone 3
    PERSONALIZED = "personalized"
    COLD_START = "cold_start"
    ARTIST_RADIO = "artist_radio"


class PopularKind(StrEnum):
    ALL_TIME = "all_time"
    TRENDING = "trending"


class RecommendationItem(BaseModel):
    track_id: uuid.UUID
    title: str
    artist: str
    score: float = Field(description="The ranking score the model computed (higher is better).")
    reason: str = Field(description="Why the track was recommended, from recorded evidence.")


class RecommendationResponse(BaseModel):
    request_id: uuid.UUID
    model_version: str = Field(description="Version of the model that produced the ranking.")
    model_versions: dict[str, str] = Field(
        description="Every model version that contributed, by model type."
    )
    strategy: Strategy
    recommendations: list[RecommendationItem]


# --- Milestone 3: personalized recommendations ---------------------------------------------


class CandidateSourceOut(BaseModel):
    """Where a recommended track came from: one candidate source that retrieved it."""

    source: str
    retrieval_score: float
    rank: int
    model_version: str | None


class PersonalizedItem(RecommendationItem):
    discovery: bool = Field(description="By an artist the user has not listened to before.")
    sources: list[CandidateSourceOut]


class SourceStatusOut(BaseModel):
    source: str
    status: str
    candidates: int
    model_version: str | None
    detail: str | None


class Composition(BaseModel):
    familiar: int
    discovery: int
    discovery_target: float | None
    exploration_mode: str
    diversity_policy: str


class PersonalizedResponse(RecommendationResponse):
    user_id: uuid.UUID | None
    profile_version: str | None
    ranker: str
    composition: Composition
    candidate_sources: list[SourceStatusOut]
    recommendations: list[PersonalizedItem]  # type: ignore[assignment]
