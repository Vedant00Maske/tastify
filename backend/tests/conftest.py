"""Shared fixtures.

Test service URLs are written to the environment before any application module is imported, so the
module-level engine and Redis client point at the isolated test database and Redis DB index.
"""

import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://tastify:tastify@127.0.0.1:5432/tastify_test"
)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="session", autouse=True)
async def _close_shared_connections() -> AsyncIterator[None]:
    yield
    from app.core.database import engine
    from app.core.redis import redis_client

    await redis_client.aclose()
    await engine.dispose()
