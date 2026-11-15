"""Shared async Redis client used for caching and online features."""

from redis.asyncio import Redis

from app.core.config import get_settings

redis_client = Redis.from_url(get_settings().redis_url, decode_responses=True)


async def get_redis() -> Redis:
    """FastAPI dependency returning the shared Redis client."""
    return redis_client
