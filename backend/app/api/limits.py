"""Client addresses and rate-limit dependencies shared by the routes."""

import ipaddress
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.redis import get_redis
from app.domains.auth import rate_limit
from app.domains.auth.dependencies import optional_user
from app.domains.users.models import User

logger = logging.getLogger(__name__)


def trusted_peer(peer: str, proxies: list[str]) -> bool:
    """Whether `peer` is one of the configured proxies (addresses or networks, e.g. a Docker
    network range)."""
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for proxy in proxies:
        try:
            if address in ipaddress.ip_network(proxy, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request) -> str:
    """The caller's address. X-Forwarded-For is trusted only from configured proxies (the reverse
    proxy or the Next.js server in front of the API); its first entry is the client, because those
    proxies replace a header they received from an untrusted client."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and trusted_peer(peer, get_settings().trusted_proxies):
        return forwarded.split(",")[0].strip()
    return peer


def too_many(error: rate_limit.RateLimitedError) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail=str(error),
        headers={"Retry-After": str(error.retry_after)},
    )


def rate_limited(
    limit: rate_limit.Limit, per: Literal["user", "client"] = "client"
) -> Callable[..., Awaitable[None]]:
    """A route dependency counting one attempt per signed-in user or per client address.

    These limits protect capacity, not credentials, so they fail open: if Redis is unreachable
    the request proceeds (and is logged) instead of failing."""

    async def dependency(
        request: Request,
        redis: Annotated[Redis, Depends(get_redis)],
        user: Annotated[User | None, Depends(optional_user)],
    ) -> None:
        key = str(user.id) if per == "user" and user is not None else client_ip(request)
        try:
            await rate_limit.hit(redis, limit, key)
        except rate_limit.RateLimitedError as error:
            raise too_many(error) from error
        except RedisError:
            logger.warning("Rate limit %s not checked: Redis unavailable", limit.name)

    return dependency


def limit(limit_: rate_limit.Limit, per: Literal["user", "client"] = "client") -> Any:
    """`dependencies=[limit(...)]` shorthand."""
    return Depends(rate_limited(limit_, per))
