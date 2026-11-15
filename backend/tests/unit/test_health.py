from httpx import AsyncClient

from app import __version__
from app.core.database import get_db_session
from app.core.redis import get_redis
from app.main import app


class _UnreachableDatabase:
    async def execute(self, *_args: object, **_kwargs: object) -> None:
        raise ConnectionRefusedError("database is down")


class _UnreachableRedis:
    async def ping(self) -> bool:
        raise ConnectionRefusedError("redis is down")


async def test_liveness_reports_ok_without_touching_dependencies(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_readiness_returns_503_when_dependencies_are_unreachable(
    client: AsyncClient,
) -> None:
    app.dependency_overrides[get_db_session] = _UnreachableDatabase
    app.dependency_overrides[get_redis] = _UnreachableRedis

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "unavailable", "redis": "unavailable"},
    }
