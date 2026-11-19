import pytest

from app.core.redis import redis_client
from tests.integration.catalogue.conftest import session

__all__ = ["session"]


@pytest.fixture(autouse=True)
async def _fresh_redis() -> None:
    """Rate limits, OAuth states and quota counters live in Redis (test DB 15)."""
    await redis_client.flushdb()
