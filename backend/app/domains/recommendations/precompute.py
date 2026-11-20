"""Precomputed personal mixes (Milestone 7, ADR-020; spec §4 "cached and precomputed").

After a user's feedback is recorded, the worker computes their for-you and hidden-gems mixes for
the new state and stores them in the response cache, so the next home page is served from the
cache instead of waiting for a ranking. The requests warmed are the web app's defaults (FOR_YOU
and HIDDEN_GEMS below); anything else is computed on demand as before.

Precomputed responses are not logged: logging happens when a response is actually served.
"""

import asyncio
import logging
import time
import uuid
from functools import partial
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.recommendations import logging_service
from app.domains.recommendations.personalized import (
    PersonalizedRecommendationService,
    RequestContext,
)
from app.domains.recommendations.response_cache import (
    ResponseCache,
    for_you_request,
    hidden_gems_request,
)
from app.domains.recommendations.schemas import PersonalizedResponse
from app.domains.recommendations.service import RecommendationError

logger = logging.getLogger(__name__)

# The web app's home page requests (frontend services/api.ts): forYou(25), hiddenGems(20).
FOR_YOU_LIMIT = 25
HIDDEN_GEMS_LIMIT = 20


def _zone(name: str | None) -> RequestContext:
    try:
        return RequestContext(zone=ZoneInfo(name) if name else None)
    except (ZoneInfoNotFoundError, ValueError):
        return RequestContext()


async def warm(
    session: AsyncSession, redis: Redis, user_id: uuid.UUID, zone: str | None
) -> list[str]:
    """Compute and cache the default mixes for the user's current state; returns the surfaces
    computed (already-cached ones are skipped)."""
    cache = ResponseCache(redis)
    if not cache.enabled:
        return []
    context = _zone(zone)
    service = PersonalizedRecommendationService(session)
    assignment = await logging_service.assignment_for(session, "for_you", user_id)
    params = assignment.params if assignment else None
    computed: list[str] = []

    async def for_you() -> PersonalizedResponse:
        computed.append("for_you")
        return await service.for_you(user_id, FOR_YOU_LIMIT, request_context=context, params=params)

    async def hidden_gems() -> PersonalizedResponse:
        computed.append("hidden_gems")
        return await service.for_you(
            user_id, HIDDEN_GEMS_LIMIT, collection="hidden_gems", request_context=context
        )

    started = time.perf_counter()
    try:
        await cache.get_or_compute(
            session,
            "for_you",
            user_id,
            for_you_request(FOR_YOU_LIMIT, None, params, zone),
            PersonalizedResponse,
            for_you,
            keep=lambda r: bool(r.recommendations),
        )
        await session.commit()  # a rebuilt taste profile is kept
        await cache.get_or_compute(
            session,
            "hidden_gems",
            user_id,
            hidden_gems_request(HIDDEN_GEMS_LIMIT, zone),
            PersonalizedResponse,
            hidden_gems,
            keep=lambda r: bool(r.recommendations),
        )
        await session.commit()
    except RecommendationError:
        logger.info("precompute skipped user=%s (models unavailable)", user_id)
        return computed
    logger.info(
        "precomputed user=%s surfaces=%s in %.0f ms",
        user_id,
        ",".join(computed) or "none (cached)",
        (time.perf_counter() - started) * 1000,
    )
    return computed


# Feedback often arrives in bursts (a like right after a play): wait briefly, so one job sees the
# whole burst. Jobs for an older state are harmless; they only fill a key nobody asks for.
SCHEDULE_DELAY_SECONDS = 2


class PrecomputeScheduler:
    """Queues a precompute job (FastAPI dependency; tests replace it)."""

    async def schedule(self, user_id: uuid.UUID, zone: str | None) -> None:
        from app.workers.tasks import precompute_recommendations

        try:
            queue = partial(
                precompute_recommendations.apply_async,
                args=(str(user_id), zone),
                countdown=SCHEDULE_DELAY_SECONDS,
            )
            await asyncio.to_thread(queue)
        except Exception:  # broker unavailable: the next request computes instead
            logger.warning("precompute not queued user=%s", user_id)


class NoPrecompute(PrecomputeScheduler):
    async def schedule(self, user_id: uuid.UUID, zone: str | None) -> None:
        return None


def get_precompute_scheduler() -> PrecomputeScheduler:
    settings = get_settings()
    if settings.recommendation_precompute and settings.recommendation_cache_seconds > 0:
        return PrecomputeScheduler()
    return NoPrecompute()
