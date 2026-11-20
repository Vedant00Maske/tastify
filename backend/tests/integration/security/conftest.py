import pytest

from app.core.redis import redis_client
from tests.integration.catalogue.conftest import session

__all__ = ["session"]


@pytest.fixture(autouse=True)
async def _fresh_rate_limits() -> None:
    """Rate-limit counters live in Redis (test DB 15); every test starts from zero."""
    await redis_client.flushdb()
