"""Liveness and readiness probes."""

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.database import get_db_session
from app.core.redis import get_redis
from app.schemas.health import CheckStatus, HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

DEPENDENCY_CHECK_TIMEOUT_SECONDS = 2.0

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def liveness() -> HealthResponse:
    """The process is up. Does not touch external dependencies."""
    return HealthResponse(status="ok", version=__version__)


@router.get(
    "/ready",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readiness(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> ReadinessResponse:
    """The service can handle traffic: PostgreSQL and Redis are reachable."""
    checks: dict[str, CheckStatus] = {
        "database": await _check_database(session),
        "redis": await _check_redis(redis),
    }
    ready = all(result == "ok" for result in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ok" if ready else "unavailable", checks=checks)


async def _check_database(session: AsyncSession) -> CheckStatus:
    try:
        async with asyncio.timeout(DEPENDENCY_CHECK_TIMEOUT_SECONDS):
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Readiness check failed: database", exc_info=True)
        return "unavailable"
    return "ok"


async def _check_redis(redis: Redis) -> CheckStatus:
    try:
        async with asyncio.timeout(DEPENDENCY_CHECK_TIMEOUT_SECONDS):
            await redis.ping()
    except Exception:
        logger.warning("Readiness check failed: redis", exc_info=True)
        return "unavailable"
    return "ok"
