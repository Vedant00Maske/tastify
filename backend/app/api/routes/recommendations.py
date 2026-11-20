"""Recommendation endpoints (Milestones 2-4; API_SPEC.md)."""

import time
import uuid
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.limits import limit
from app.core.database import get_db_session
from app.core.redis import get_redis
from app.domains.auth import rate_limit
from app.domains.auth.dependencies import CurrentUser, optional_user
from app.domains.recommendations import logging_service
from app.domains.recommendations.custom import (
    CustomIn,
    CustomPlaylistService,
    CustomResponse,
    PromptNotUnderstoodError,
)
from app.domains.recommendations.moods import (
    MoodListResponse,
    MoodMixResponse,
    MoodService,
    describe_moods,
)
from app.domains.recommendations.personalized import (
    PersonalizedRecommendationService,
    RequestContext,
)
from app.domains.recommendations.ranking import DEFAULT_MAX_PER_ARTIST
from app.domains.recommendations.response_cache import (
    ResponseCache,
    for_you_request,
    hidden_gems_request,
)
from app.domains.recommendations.schemas import (
    BecauseYouListenedResponse,
    PersonalizedResponse,
    PopularKind,
    RecommendationResponse,
)
from app.domains.recommendations.service import (
    ModelUnavailableError,
    NotFoundError,
    NotInModelError,
    RecommendationError,
    RecommendationService,
)
from app.domains.users.models import User
from app.domains.users.profile import ExplorationMode

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

Limit = Annotated[int, Query(ge=1, le=50, description="Number of recommendations")]


def get_recommendation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RecommendationService:
    return RecommendationService(session)


Recommendations = Annotated[RecommendationService, Depends(get_recommendation_service)]


def request_context(
    x_timezone: Annotated[
        str | None,
        Header(max_length=64, description="The viewer's IANA time zone, e.g. Europe/Berlin"),
    ] = None,
) -> RequestContext:
    """The viewer's time zone, when the browser sent a valid one."""
    zone = None
    if x_timezone:
        try:
            zone = ZoneInfo(x_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            zone = None
    return RequestContext(zone=zone)


Context = Annotated[RequestContext, Depends(request_context)]


def get_response_cache(redis: Annotated[Redis, Depends(get_redis)]) -> ResponseCache:
    return ResponseCache(redis)


Cache = Annotated[ResponseCache, Depends(get_response_cache)]


def _has_items(response: PersonalizedResponse) -> bool:
    # An empty mix may only mean the catalogue or models are not loaded yet: compute again.
    return bool(response.recommendations)


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


# --- Milestone 4: personal collections (signed-in user) --------------------------------------


@router.get("/for-you")
async def for_you(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: CurrentUser,
    context: Context,
    cache: Cache,
    http: Response,
    limit: Limit = 25,
    exploration: Annotated[
        ExplorationMode | None,
        Query(description="Override the user's exploration mode for this request"),
    ] = None,
) -> PersonalizedResponse:
    """The personal mix: hybrid ranking over every candidate source, diversified, balancing
    familiar artists and discoveries (familiar 80/20, balanced 50/50, explorer 20/80), nudged by
    the current session. Logged, and assigned to the running for-you experiment if any."""
    started = time.perf_counter()
    assignment = await logging_service.assignment_for(session, "for_you", user.id)
    params = assignment.params if assignment else None

    async def compute() -> PersonalizedResponse:
        computed = await PersonalizedRecommendationService(session).for_you(
            user.id, limit, exploration, request_context=context, params=params
        )
        await session.commit()
        return computed

    try:
        response = await cache.get_or_compute(
            session,
            "for_you",
            user.id,
            for_you_request(limit, exploration, params, context.zone_name),
            PersonalizedResponse,
            compute,
            keep=_has_items,
        )
    except RecommendationError as error:
        raise _http_error(error) from error
    http.headers["X-Cache"] = "hit" if cache.last_hit else "miss"
    if assignment:
        response = response.model_copy(
            update={"experiment": assignment.experiment, "variant": assignment.variant}
        )
    await logging_service.record(
        session,
        response,
        user_id=user.id,
        category="for_you",
        assignment=assignment,
        context=response.context,
        latency_ms=round((time.perf_counter() - started) * 1000),
    )
    return response


@router.get("/hidden-gems")
async def hidden_gems(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: CurrentUser,
    context: Context,
    cache: Cache,
    http: Response,
    limit: Limit = 20,
) -> PersonalizedResponse:
    """Lesser-known tracks that match the user's taste, mostly by artists new to them."""
    started = time.perf_counter()

    async def compute() -> PersonalizedResponse:
        computed = await PersonalizedRecommendationService(session).for_you(
            user.id, limit, collection="hidden_gems", request_context=context
        )
        await session.commit()
        return computed

    try:
        response = await cache.get_or_compute(
            session,
            "hidden_gems",
            user.id,
            hidden_gems_request(limit, context.zone_name),
            PersonalizedResponse,
            compute,
            keep=_has_items,
        )
    except RecommendationError as error:
        raise _http_error(error) from error
    http.headers["X-Cache"] = "hit" if cache.last_hit else "miss"
    await logging_service.record(
        session,
        response,
        user_id=user.id,
        category="hidden_gems",
        context=response.context,
        latency_ms=round((time.perf_counter() - started) * 1000),
    )
    return response


@router.get("/surprise")
async def surprise(
    session: Annotated[AsyncSession, Depends(get_db_session)], user: CurrentUser
) -> PersonalizedResponse:
    """One discovery, picked at random from the user's top explorer-mode recommendations."""
    try:
        response = await PersonalizedRecommendationService(session).surprise(user.id)
        await session.commit()
    except RecommendationError as error:
        raise _http_error(error) from error
    await logging_service.record(session, response, user_id=user.id, category="surprise")
    return response


@router.get("/because-you-listened")
async def because_you_listened(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: CurrentUser,
    cache: Cache,
    http: Response,
    seeds: Annotated[int, Query(ge=1, le=5)] = 2,
    limit: Limit = 10,
) -> BecauseYouListenedResponse:
    """For the user's strongest recent tracks: what listeners of each also play."""

    async def compute() -> BecauseYouListenedResponse:
        sections = await PersonalizedRecommendationService(session).because_you_listened(
            user.id, seeds, limit
        )
        return BecauseYouListenedResponse(sections=sections)

    try:
        result = await cache.get_or_compute(
            session,
            "because_you_listened",
            user.id,
            {"seeds": seeds, "limit": limit},
            BecauseYouListenedResponse,
            compute,
            keep=lambda response: bool(response.sections),
        )
    except RecommendationError as error:
        raise _http_error(error) from error
    http.headers["X-Cache"] = "hit" if cache.last_hit else "miss"
    return result


@router.post("/custom", dependencies=[limit(rate_limit.PROMPT_PER_CLIENT)])
async def custom_playlist(
    data: CustomIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User | None, Depends(optional_user)],
) -> CustomResponse:
    """A playlist from a prompt (spec §9, FR-016): the prompt is read into genres, moods,
    artists and constraints (returned as `interpretation`), and tracks are ranked on catalogue
    evidence; personalized when signed in. 422 when nothing in the prompt matches the
    catalogue."""
    started = time.perf_counter()
    try:
        response = await CustomPlaylistService(session).generate(data, user.id if user else None)
    except PromptNotUnderstoodError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": str(error),
                "code": "prompt_not_understood",
                "ignored": error.ignored,
            },
        ) from error
    except RecommendationError as error:
        raise _http_error(error) from error
    if user is not None:
        await logging_service.record(
            session,
            response,
            user_id=user.id,
            category="custom",
            context={"prompt": data.prompt[:300], "summary": response.interpretation.summary},
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    return response


@router.get("/moods")
async def moods() -> MoodListResponse:
    """The available mood mixes (configured recipes)."""
    return describe_moods()


@router.get("/mood/{mood}")
async def mood_mix(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User | None, Depends(optional_user)],
    mood: Annotated[str, Path(min_length=1, max_length=64, examples=["midnight-drive"])],
    limit: Limit = 25,
    exclude: Annotated[
        list[uuid.UUID],
        Query(max_length=100, description="Tracks to leave out (regenerate a mix)"),
    ] = [],  # noqa: B006 - FastAPI copies query defaults per request
) -> MoodMixResponse:
    """A mood mix, personalized when signed in; `exclude` gives a fresh mix on regenerate."""
    try:
        response = await MoodService(session).mix(mood, limit, user.id if user else None, exclude)
    except RecommendationError as error:
        raise _http_error(error) from error
    if user is not None:
        await logging_service.record(session, response, user_id=user.id, category="mood")
    return response
