"""Fixed-window rate limits in Redis (spec §9: endpoints enforce appropriate rate limits).

Counters live in Redis, so limits hold across any number of API processes. The increment and the
window's expiry are set in one atomic script: a crash between the two can never leave a counter
without an expiry (which would lock a key out for good).
"""

from dataclasses import dataclass

from redis.asyncio import Redis

from app.core import metrics


@dataclass(frozen=True)
class Limit:
    name: str
    attempts: int
    window_seconds: int


MINUTE = 60
HOUR = 60 * MINUTE

# Accounts (Milestone 4).
LOGIN_PER_ACCOUNT = Limit("login-account", attempts=10, window_seconds=15 * MINUTE)
LOGIN_PER_CLIENT = Limit("login-client", attempts=30, window_seconds=15 * MINUTE)
REGISTER_PER_CLIENT = Limit("register-client", attempts=10, window_seconds=HOUR)
# Signed-in password confirmations (password change, account deletion): without a limit a stolen
# session could be used to guess the password.
PASSWORD_CONFIRM_PER_USER = Limit("password-confirm", attempts=10, window_seconds=15 * MINUTE)
# Password reset and e-mail verification (Milestone 7).
RESET_REQUEST_PER_CLIENT = Limit("reset-request-client", attempts=10, window_seconds=HOUR)
RESET_REQUEST_PER_ACCOUNT = Limit("reset-request-account", attempts=3, window_seconds=HOUR)
TOKEN_SUBMIT_PER_CLIENT = Limit("token-submit-client", attempts=30, window_seconds=HOUR)
VERIFICATION_PER_USER = Limit("verification-user", attempts=5, window_seconds=HOUR)

# Expensive or abusable endpoints (Milestone 7).
SEARCH_PER_CLIENT = Limit("search-client", attempts=120, window_seconds=MINUTE)
PROMPT_PER_CLIENT = Limit("prompt-client", attempts=30, window_seconds=MINUTE)
MUSICBRAINZ_PER_CLIENT = Limit("musicbrainz-client", attempts=30, window_seconds=MINUTE)
IMPORT_PER_USER = Limit("import-user", attempts=10, window_seconds=HOUR)
EXPORT_PER_USER = Limit("export-user", attempts=30, window_seconds=HOUR)
DATA_EXPORT_PER_USER = Limit("data-export-user", attempts=10, window_seconds=HOUR)
INTERACTIONS_PER_USER = Limit("interactions-user", attempts=600, window_seconds=MINUTE)
CLIENT_ERRORS_PER_CLIENT = Limit("client-errors-client", attempts=30, window_seconds=MINUTE)

_HIT = """
local count = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""


class RateLimitedError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many attempts; try again later")
        self.retry_after = retry_after


def _key(limit: Limit, key: str) -> str:
    return f"ratelimit:{limit.name}:{key}"


async def hit(redis: Redis, limit: Limit, key: str) -> None:
    """Count one attempt; raise RateLimitedError once the window's budget is spent."""
    count, ttl = await redis.eval(_HIT, 1, _key(limit, key), limit.window_seconds)
    if int(count) > limit.attempts:
        metrics.RATE_LIMITED.labels(limit.name).inc()
        raise RateLimitedError(max(int(ttl), 1))


async def reset(redis: Redis, limit: Limit, key: str) -> None:
    await redis.delete(_key(limit, key))
