"""Recommendation endpoints (Milestones 2 and 3; API_SPEC.md)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.domains.recommendations.personalized import PersonalizedRecommendationService
from app.domains.recommendations.ranking import DEFAULT_MAX_PER_ARTIST
from app.domains.recommendations.schemas import PopularKind, RecommendationResponse
from app.domains.recommendations.service import (
    ModelUnavailableError,
    NotFoundError,
    NotInModelError,
    RecommendationError,
    RecommendationService,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

Limit = Annotated[int, Query(ge=1, le=50, description="Number of recommendations")]


def get_recommendation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RecommendationService:
    return RecommendationService(session)


Recommendations = Annotated[RecommendationService, Depends(get_recommendation_service)]


def _http_error(error: RecommendationError) -> HTTPException:
    if isinstance(error, NotFoundError | NotInModelError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, ModelUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    raise error


@router.get("/similar/{track_id}")
async def similar_tracks(
    service: Recommendations,
    track_id: uuid.UUID,
    limit: Limit = 20,
    max_per_artist: Annotated[
        int, Query(ge=1, le=50, description="At most this many tracks per artist")
    ] = DEFAULT_MAX_PER_ARTIST,
) -> RecommendationResponse:
    """Tracks similar to a favourite track (content-based, popularity-aware)."""
    try:
        return await service.similar_tracks(track_id, limit, max_per_artist)
    except RecommendationError as error:
        raise _http_error(error) from error


@router.get("/artist/{artist_id}")
async def similar_artists(
    service: Recommendations, artist_id: uuid.UUID, limit: Limit = 20
) -> RecommendationResponse:
    """Popular tracks by the artists most similar to this one."""
    try:
        return await service.similar_artists(artist_id, limit)
    except RecommendationError as error:
        raise _http_error(error) from error


@router.get("/genre/{genre}")
async def genre(
    service: Recommendations,
    genre: Annotated[str, Path(min_length=1, max_length=100, examples=["alternative rock"])],
    limit: Limit = 20,
) -> RecommendationResponse:
    """Popular tracks that are strongly tagged with a genre."""
    try:
        return await service.genre(genre, limit)
    except RecommendationError as error:
        raise _http_error(error) from error


@router.get("/popular")
async def popular(
    service: Recommendations,
    limit: Limit = 20,
    kind: PopularKind = PopularKind.ALL_TIME,
    artist_id: Annotated[uuid.UUID | None, Query(description="Only this artist's tracks")] = None,
) -> RecommendationResponse:
    """Most listened tracks over the popularity window, or reliably trending tracks."""
    try:
        return await service.popular(limit, kind, artist_id)
    except RecommendationError as error:
        raise _http_error(error) from error


@router.get("/artist-radio/{artist_id}")
async def artist_radio(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    artist_id: uuid.UUID,
    limit: Limit = 25,
) -> RecommendationResponse:
    """An artist radio: the artist's popular tracks (up to 40% of the list) mixed with tracks by
    similar artists, diversified with MMR."""
    try:
        return await PersonalizedRecommendationService(session).artist_radio(artist_id, limit)
    except RecommendationError as error:
        raise _http_error(error) from error
