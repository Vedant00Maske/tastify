"""Daily provider quotas, counted in Redis (YouTube Data API units; ADR-018).

The day follows the provider's reset (YouTube: midnight Pacific time). Units are reserved
atomically before each call, so concurrent exports cannot overshoot the budget together.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from redis.asyncio import Redis

from app.domains.integrations.providers.base import QuotaExceededError

PACIFIC = ZoneInfo("America/Los_Angeles")

# KEYS[1] counter; ARGV[1] units, ARGV[2] budget. Returns the new total, or -1 if over budget.
_RESERVE = """
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
local units = tonumber(ARGV[1])
if used + units > tonumber(ARGV[2]) then return -1 end
local total = redis.call('INCRBY', KEYS[1], units)
redis.call('EXPIRE', KEYS[1], 172800)
return total
"""


class QuotaMeter:
    def __init__(self, redis: Redis, provider: str, budget: int) -> None:
        self.redis = redis
        self.provider = provider
        self.budget = budget

    def _key(self) -> str:
        return f"quota:{self.provider}:{datetime.now(PACIFIC).date().isoformat()}"

    async def used(self) -> int:
        return int(await self.redis.get(self._key()) or 0)

    async def remaining(self) -> int:
        return max(0, self.budget - await self.used())

    async def require(self, units: int) -> None:
        """Fail before starting an operation that could need more than what is left."""
        left = await self.remaining()
        if units > left:
            raise QuotaExceededError(self.provider, needed=units, remaining=left)

    async def spend(self, units: int) -> None:
        total = await self.redis.eval(_RESERVE, 1, self._key(), units, self.budget)
        if int(total) < 0:
            raise QuotaExceededError(self.provider, needed=units, remaining=await self.remaining())
