"""Per-user cache of personalized responses (Milestone 7, ADR-020; spec §4: p95 below 500 ms for
cached and precomputed recommendations).

The key is a fingerprint of everything a personal ranking depends on, read in one query:

- the user's events (latest receipt time and count: events are append-only, and deleting
  imported history changes the count),
- the declared preferences (their values, not timestamps),
- the active model versions,

plus the request (surface, limit, exploration override, experiment parameters, time zone). Any
new feedback, preference change or model publication therefore produces a different key: a
stale response is never served, it simply stops being asked for and expires. The time-based
part of ranking (the current session's last hour) is bounded by the short lifetime
(RECOMMENDATION_CACHE_SECONDS).

A cached response gets a fresh `request_id` each time it is served, so logging and feedback
attribution work exactly as for a computed one. Entries are compressed; Redis failures fall
back to computing.
"""

import base64
import hashlib
import json
import logging
import uuid
import zlib
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.config import get_settings

logger = logging.getLogger(__name__)

PREFIX = "reccache:v1"

Model = TypeVar("Model", bound=BaseModel)

_STATE = text(
    """
    SELECT
      (SELECT max(received_at)::text || ':' || count(*)
         FROM user_interactions WHERE user_id = :user) AS events,
      (SELECT coalesce(exploration_mode, '') || ':' || personalization_enabled::text || ':'
              || array_to_string(preferred_moods, ',')
         FROM user_preferences WHERE user_id = :user) AS preferences,
      (SELECT string_agg(artist_id::text || preference, ',' ORDER BY artist_id)
         FROM user_artist_preferences WHERE user_id = :user) AS artists,
      (SELECT string_agg(genre_id::text || preference, ',' ORDER BY genre_id)
         FROM user_genre_preferences WHERE user_id = :user) AS genres,
      (SELECT string_agg(id::text, ',' ORDER BY id)
         FROM model_versions WHERE status = 'active') AS models
    """
)


async def state_fingerprint(session: AsyncSession, user_id: uuid.UUID) -> str:
    row = (await session.execute(_STATE, {"user": user_id})).one()
    return hashlib.sha256("|".join(str(v) for v in row).encode()).hexdigest()


def cache_key(surface: str, user_id: uuid.UUID, state: str, request: dict[str, Any]) -> str:
    parts = json.dumps(request, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{state}|{parts}".encode()).hexdigest()[:32]
    return f"{PREFIX}:{surface}:{user_id}:{digest}"


def for_you_request(
    limit: int, mode: str | None, params: Mapping[str, Any] | None, zone: str | None
) -> dict[str, Any]:
    """The request part of a for-you key (shared by the route and the precompute job)."""
    return {
        "limit": limit,
        "mode": None if mode is None else str(mode),
        "params": params,
        "zone": zone,
    }


def hidden_gems_request(limit: int, zone: str | None) -> dict[str, Any]:
    return {"limit": limit, "zone": zone}


class ResponseCache:
    def __init__(self, redis: Redis, ttl_seconds: int | None = None) -> None:
        self.redis = redis
        self.ttl = (
            get_settings().recommendation_cache_seconds if ttl_seconds is None else ttl_seconds
        )

    @property
    def enabled(self) -> bool:
        return self.ttl > 0

    async def get(self, key: str, model: type[Model]) -> Model | None:
        try:
            raw = await self.redis.get(key)
        except RedisError:
            logger.warning("recommendation cache unavailable (read)")
            return None
        if raw is None:
            return None
        response = model.model_validate_json(zlib.decompress(base64.b64decode(raw)))
        if "request_id" in model.model_fields:
            response = response.model_copy(update={"request_id": uuid.uuid4()})
        return response

    async def put(self, key: str, response: BaseModel) -> None:
        compressed = zlib.compress(response.model_dump_json().encode(), level=6)
        try:
            # Base64 text: the shared Redis client decodes replies as strings.
            await self.redis.set(key, base64.b64encode(compressed).decode(), ex=self.ttl)
        except RedisError:
            logger.warning("recommendation cache unavailable (write)")

    async def contains(
        self, session: AsyncSession, surface: str, user_id: uuid.UUID, request: dict[str, Any]
    ) -> bool:
        """Whether a response for the user's current state is already cached."""
        key = cache_key(surface, user_id, await state_fingerprint(session, user_id), request)
        try:
            return bool(await self.redis.exists(key))
        except RedisError:
            return False

    async def get_or_compute(
        self,
        session: AsyncSession,
        surface: str,
        user_id: uuid.UUID,
        request: dict[str, Any],
        model: type[Model],
        compute: Callable[[], Awaitable[Model]],
        keep: Callable[[Model], bool] = lambda _: True,
    ) -> Model:
        self.last_hit = False
        if not self.enabled:
            return await compute()
        key = cache_key(surface, user_id, await state_fingerprint(session, user_id), request)
        cached = await self.get(key, model)
        metrics.cache_lookup(f"recommendations_{surface}", hit=cached is not None)
        if cached is not None:
            self.last_hit = True
            return cached
        response = await compute()
        if keep(response):
            await self.put(key, response)
        return response
