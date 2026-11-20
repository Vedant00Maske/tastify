"""Production hardening (Milestone 7, ADR-020): request context, headers, body limits, metrics,
error handling, startup checks and scheduled pruning."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.core.config import Settings, get_settings
from app.core.database import SessionFactory
from app.core.middleware import RequestContextMiddleware
from app.domains import maintenance
from app.domains.auth import rate_limit
from app.domains.users.models import AccountToken, User, UserSession

pytestmark = pytest.mark.integration


async def test_responses_carry_security_headers_and_a_request_id(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    headers = response.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cache-control"] == "no-store"
    assert headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert "strict-transport-security" not in headers  # only when deployed (HTTPS)
    assert len(headers["x-request-id"]) == 32

    kept = await client.get("/api/v1/health", headers={"X-Request-ID": "proxy-abc-12345"})
    assert kept.headers["x-request-id"] == "proxy-abc-12345"
    replaced = await client.get("/api/v1/health", headers={"X-Request-ID": "bad id\r\nx: y"})
    assert replaced.headers["x-request-id"] != "bad id\r\nx: y"


async def test_oversized_bodies_are_refused(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import app

    limit = get_settings().max_request_body_bytes
    declared = await client.post(
        "/api/v1/interactions", content=b"x" * (limit + 1), headers={"content-type": "text/plain"}
    )
    assert declared.status_code == 413

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(3):
            yield b"y" * (limit // 2 + 1)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as streaming:
        streamed = await streaming.post("/api/v1/auth/login", content=chunks())
    assert streamed.status_code == 413


async def test_unhandled_errors_are_generic_and_traceable() -> None:
    app = FastAPI()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    app.add_middleware(RequestContextMiddleware)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error"
    assert body["request_id"] == response.headers["x-request-id"]
    assert "hunter2" not in response.text


async def test_metrics_are_exposed_and_can_require_a_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.get("/api/v1/health")
    await client.get("/api/v1/genres")
    scrape = await client.get("/metrics")
    assert scrape.status_code == 200
    body = scrape.text
    assert "soniqueo_http_requests_total" in body
    assert 'route="/genres"' in body or 'route="/api/v1/genres"' in body
    assert "soniqueo_db_query_duration_seconds_bucket" in body
    assert "soniqueo_http_requests_in_flight" in body

    monkeypatch.setattr(get_settings(), "metrics_token", "scrape-secret")
    assert (await client.get("/metrics")).status_code == 401
    authorised = await client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"})
    assert authorised.status_code == 200


async def test_rate_limit_counters_always_expire(client: AsyncClient) -> None:
    from app.core.redis import redis_client

    key = f"ratelimit:{rate_limit.SEARCH_PER_CLIENT.name}:203.0.113.9"
    await redis_client.set(key, 5)  # a counter left without expiry (the old race)
    await rate_limit.hit(redis_client, rate_limit.SEARCH_PER_CLIENT, "203.0.113.9")
    assert 0 < await redis_client.ttl(key) <= rate_limit.SEARCH_PER_CLIENT.window_seconds


async def test_search_and_prompts_are_rate_limited(client: AsyncClient) -> None:
    statuses = [
        (await client.get("/api/v1/tracks/search", params={"q": "a"})).status_code
        for _ in range(rate_limit.SEARCH_PER_CLIENT.attempts + 1)
    ]
    assert statuses[-1] == 429
    assert statuses[:-1].count(429) == 0


async def test_web_app_errors_are_accepted_and_counted(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/client-errors",
        json={"kind": "render", "message": "Boom token=abc123 happened", "path": "/home"},
    )
    assert response.status_code == 202
    bad_path = await client.post(
        "/api/v1/client-errors", json={"message": "x", "path": "/home?token=abc"}
    )
    assert bad_path.status_code == 422
    scrape = await client.get("/metrics")
    assert 'soniqueo_client_errors_total{kind="render"}' in scrape.text


def test_deployment_settings_are_checked() -> None:
    unsafe = Settings(_env_file=None, environment="production")
    problems = unsafe.deployment_problems()
    assert any("CORS_ORIGINS" in p for p in problems)
    assert any("APP_PUBLIC_URL" in p for p in problems)
    assert any("DATABASE_URL" in p for p in problems)
    assert any("SMTP_HOST" in p for p in problems)
    assert unsafe.api_docs_enabled is False
    assert unsafe.session_cookie_secure is True

    safe = Settings(
        _env_file=None,
        environment="production",
        cors_origins=["https://soniqueo.example"],
        app_public_url="https://soniqueo.example",
        database_url="postgresql+asyncpg://soniqueo:s3cret-long@postgres:5432/soniqueo",
        smtp_host="smtp.example",
    )
    assert safe.deployment_problems() == []


def test_production_refuses_unsafe_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as main

    unsafe = Settings(_env_file=None, environment="production")
    monkeypatch.setattr(main, "get_settings", lambda: unsafe)
    with pytest.raises(main.UnsafeConfigurationError, match="SMTP_HOST"):
        main.create_app()
    staging = Settings(_env_file=None, environment="staging")
    monkeypatch.setattr(main, "get_settings", lambda: staging)
    assert main.create_app() is not None  # staging only warns


async def test_prune_enforces_retention(migrated_database: None) -> None:
    now = datetime.now(UTC)
    async with SessionFactory() as session:
        await session.execute(text("TRUNCATE users CASCADE"))
        user = User(
            email=f"prune-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="not-a-real-hash",  # noqa: S106 - test row
            terms_accepted_at=now,
        )
        session.add(user)
        await session.flush()
        old = now - timedelta(days=10)
        session.add_all(
            [
                UserSession(
                    user_id=user.id,
                    token_hash="a" * 64,
                    expires_at=now - timedelta(hours=1),
                    last_seen_at=old,
                ),
                UserSession(
                    user_id=user.id,
                    token_hash="b" * 64,
                    expires_at=now + timedelta(days=5),
                    last_seen_at=old,
                    revoked_at=old,
                ),
                UserSession(
                    user_id=user.id,
                    token_hash="c" * 64,
                    expires_at=now + timedelta(days=5),
                    last_seen_at=now,
                ),
                AccountToken(
                    user_id=user.id,
                    purpose="password_reset",
                    token_hash="d" * 64,
                    email=user.email,
                    expires_at=now - timedelta(days=2),
                ),
                AccountToken(
                    user_id=user.id,
                    purpose="email_verification",
                    token_hash="e" * 64,
                    email=user.email,
                    expires_at=now + timedelta(hours=1),
                ),
            ]
        )
        await session.commit()
        result = await maintenance.prune(session)
        assert result.sessions == 2
        assert result.account_tokens == 1
        remaining = (await session.scalars(select(UserSession.token_hash))).all()
        assert remaining == ["c" * 64]
        again = await maintenance.prune(session)  # idempotent
        assert again.sessions == 0
        assert again.account_tokens == 0
        await session.execute(text("TRUNCATE users CASCADE"))
        await session.commit()
