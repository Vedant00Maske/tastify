"""Fixed-window rate limits in Redis (spec §9: endpoints enforce appropriate rate limits)."""

from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass(frozen=True)
class Limit:
    name: str
    attempts: int
    window_seconds: int


LOGIN_PER_ACCOUNT = Limit("login-account", attempts=10, window_seconds=15 * 60)
LOGIN_PER_CLIENT = Limit("login-client", attempts=30, window_seconds=15 * 60)
REGISTER_PER_CLIENT = Limit("register-client", attempts=10, window_seconds=60 * 60)


class RateLimitedError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many attempts; try again later")
        self.retry_after = retry_after


async def hit(redis: Redis, limit: Limit, key: str) -> None:
    """Count one attempt; raise RateLimitedError once the window's budget is spent."""
    redis_key = f"ratelimit:{limit.name}:{key}"
    count = await redis.incr(redis_key)
    if count == 1:
        await redis.expire(redis_key, limit.window_seconds)
    if count > limit.attempts:
        ttl = await redis.ttl(redis_key)
        raise RateLimitedError(max(int(ttl), 1))


async def reset(redis: Redis, limit: Limit, key: str) -> None:
    await redis.delete(f"ratelimit:{limit.name}:{key}")
