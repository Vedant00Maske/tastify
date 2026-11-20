import pytest

from tests.integration.migration_runner import run_alembic


@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Bring the test database schema up to the latest migration."""
    run_alembic("upgrade", "head")


@pytest.fixture(autouse=True)
async def _fresh_redis() -> None:
    """Rate-limit counters and other online state live in Redis (test DB 15): every integration
    test starts from zero, so limits added to routes never leak between tests."""
    from app.core.redis import redis_client

    await redis_client.flushdb()
