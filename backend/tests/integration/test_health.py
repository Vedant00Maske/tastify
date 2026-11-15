import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_readiness_is_ok_when_postgres_and_redis_are_reachable(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}
