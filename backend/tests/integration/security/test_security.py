"""Security tests (spec §11.6; Milestone 7 security audit, docs/reports/security-audit.md).

Broken access control and insecure direct object references, SQL injection, stored script
payloads, CSRF, rate-limit bypass, token leakage into logs, and the authentication sweep: every
API operation either is deliberately public or refuses anonymous callers.
"""

import logging
import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.auth.dependencies import SESSION_COOKIE
from app.domains.users.models import User
from tests.integration.users.test_personalization_api import World, create_user, world

pytestmark = pytest.mark.integration

__all__ = ["world"]

# Operations anyone may call. Everything else must answer 401 without a session: a new route
# fails this test until it is consciously classified.
PUBLIC = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/ready"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/password/forgot"),
    ("POST", "/api/v1/auth/password/reset"),
    ("POST", "/api/v1/auth/email/verify"),
    ("GET", "/api/v1/tracks/search"),
    ("GET", "/api/v1/tracks/lookup"),
    ("GET", "/api/v1/tracks/{track_id}"),
    ("GET", "/api/v1/artists/search"),
    ("GET", "/api/v1/genres"),
    ("GET", "/api/v1/artists/{artist_id}"),
    ("GET", "/api/v1/recommendations/similar/{track_id}"),
    ("GET", "/api/v1/recommendations/artist/{artist_id}"),
    ("GET", "/api/v1/recommendations/genre/{genre}"),
    ("GET", "/api/v1/recommendations/popular"),
    ("GET", "/api/v1/recommendations/artist-radio/{artist_id}"),
    ("GET", "/api/v1/recommendations/moods"),
    ("GET", "/api/v1/recommendations/mood/{mood}"),
    ("POST", "/api/v1/recommendations/custom"),
    ("POST", "/api/v1/client-errors"),
}

SQL_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE users; --",
    '" OR 1=1 --',
    "%' UNION SELECT email, password_hash FROM users --",
    "\\'; SELECT pg_sleep(5); --",
]
SCRIPT = '<script>alert("x")</script><img src=x onerror=alert(1)>'


def _concrete(path: str) -> str:
    return re.sub(
        r"\{[^}]+\}", lambda m: "spotify" if m.group() == "{provider}" else str(uuid.uuid4()), path
    )


def _operations() -> list[tuple[str, str]]:
    from app.main import app

    return [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    ]


async def test_every_private_operation_requires_a_session(client: AsyncClient) -> None:
    operations = _operations()
    assert len(operations) > 50
    unexpected = []
    for method, path in operations:
        if (method, path) in PUBLIC:
            continue
        response = await client.request(method, _concrete(path), json={})
        if response.status_code != 401:
            unexpected.append((method, path, response.status_code))
    assert unexpected == []
    # The OAuth callback is not in the schema; anonymous callers are sent to sign in.
    callback = await client.get("/api/v1/integrations/spotify/callback?code=a&state=b")
    assert callback.status_code == 303
    assert callback.headers["location"].endswith("/login")


async def test_a_forged_session_cookie_is_not_accepted(client: AsyncClient) -> None:
    client.cookies.set(SESSION_COOKIE, "forged-" + "a" * 40)
    assert (await client.get("/api/v1/users/me")).status_code == 401


async def test_other_users_playlists_are_out_of_reach(client: AsyncClient, world: World) -> None:
    """Insecure direct object references: every playlist operation by a stranger is a 404 (the
    playlist's existence is not revealed either) and changes nothing."""
    await create_user(client)
    track = str(world.tracks["Creep"])
    created = await client.post("/api/v1/playlists", json={"name": "Private", "track_ids": [track]})
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    before = (await client.get(f"/api/v1/playlists/{pid}")).json()

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        await create_user(other)
        attempts = [
            other.get(f"/api/v1/playlists/{pid}"),
            other.patch(f"/api/v1/playlists/{pid}", json={"name": "Stolen"}),
            other.post(f"/api/v1/playlists/{pid}/tracks", json={"track_ids": [track]}),
            other.delete(f"/api/v1/playlists/{pid}/tracks/{track}"),
            other.put(f"/api/v1/playlists/{pid}/tracks/order", json={"track_ids": [track]}),
            other.post(f"/api/v1/playlists/{pid}/regenerate"),
            other.get(f"/api/v1/playlists/{pid}/suggestions"),
            other.post(f"/api/v1/playlists/{pid}/export", json={"provider": "listenbrainz"}),
            other.get(f"/api/v1/playlists/{pid}/exports"),
            other.delete(f"/api/v1/playlists/{pid}"),
        ]
        for attempt in attempts:
            response = await attempt
            assert response.status_code == 404, (response.request.url, response.status_code)
        assert (await other.get("/api/v1/playlists")).json()["playlists"] == []
        assert (await other.get("/api/v1/integrations/imports")).json() == []
    after = (await client.get(f"/api/v1/playlists/{pid}")).json()
    assert after == before


async def test_injection_payloads_are_plain_text(
    client: AsyncClient, session: AsyncSession, world: World
) -> None:
    await create_user(client)
    users_before = await session.scalar(select(func.count()).select_from(User))
    for payload in SQL_PAYLOADS:
        for path, params in (
            ("/api/v1/tracks/search", {"q": payload}),
            ("/api/v1/artists/search", {"q": payload}),
            ("/api/v1/tracks/lookup", {"title": payload, "artist": payload}),
        ):
            response = await client.get(path, params=params)
            assert response.status_code < 500, (path, payload, response.text)
            if response.status_code == 200 and "results" in response.json():
                assert response.json()["results"] == []
        genre = await client.get(f"/api/v1/recommendations/genre/{payload}")
        assert genre.status_code < 500
        prompt = await client.post("/api/v1/recommendations/custom", json={"prompt": payload})
        assert prompt.status_code in (200, 422)
    session.expire_all()
    assert await session.scalar(select(func.count()).select_from(User)) == users_before


async def test_script_payloads_are_stored_and_returned_as_data(
    client: AsyncClient, world: World
) -> None:
    """The API returns user text verbatim as JSON, never as HTML; the web app renders it as text
    (React escapes it) and the API's CSP forbids executing anything from its responses."""
    await create_user(client)
    me = await client.patch("/api/v1/users/me", json={"display_name": SCRIPT[:80]})
    assert me.json()["display_name"] == SCRIPT[:80]
    created = await client.post("/api/v1/playlists", json={"name": SCRIPT[:100]})
    assert created.status_code == 201, created.text
    fetched = await client.get(f"/api/v1/playlists/{created.json()['id']}")
    assert fetched.json()["name"] == SCRIPT[:100]
    assert fetched.headers["content-type"].startswith("application/json")
    assert (
        fetched.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    )
    assert fetched.headers["x-content-type-options"] == "nosniff"


async def test_cross_site_requests_are_refused(client: AsyncClient) -> None:
    await create_user(client)
    response = await client.post(
        "/api/v1/playlists", json={"name": "csrf"}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    allowed = get_settings().cors_origins[0]
    ok = await client.post("/api/v1/playlists", json={"name": "fine"}, headers={"Origin": allowed})
    assert ok.status_code == 201


async def test_forwarded_addresses_cannot_dodge_rate_limits(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """X-Forwarded-For is honoured only from configured proxies; a direct client that invents a
    new address per request still shares one budget."""
    monkeypatch.setattr(get_settings(), "trusted_proxies", [])
    statuses = []
    for attempt in range(32):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": f"nobody{attempt}@example.com", "password": "wrong password 1"},
            headers={"X-Forwarded-For": f"203.0.113.{attempt}"},
        )
        statuses.append(response.status_code)
    assert statuses[:30] == [401] * 30
    assert statuses[30:] == [429, 429]


async def test_password_confirmations_are_rate_limited(client: AsyncClient) -> None:
    """A stolen session cannot be used to guess the password through the confirmation forms."""
    await create_user(client)
    statuses = [
        (
            await client.post(
                "/api/v1/auth/password",
                json={"current_password": f"guess number {i}", "new_password": "x" * 12},
            )
        ).status_code
        for i in range(11)
    ]
    assert statuses[:10] == [403] * 10
    assert statuses[10] == 429
    deletion = await client.request(
        "DELETE", "/api/v1/users/me", json={"password": "correct horse battery"}
    )
    assert deletion.status_code == 429  # the same budget covers account deletion


async def test_secrets_never_reach_the_logs(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    password = "correct horse battery"  # noqa: S105 - test credential
    email = f"logs-{uuid.uuid4().hex[:8]}@example.com"
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password, "accept_terms": True}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    cookie = login.cookies[SESSION_COOKIE]
    await client.get(
        "/api/v1/integrations/spotify/callback",
        params={"code": "provider-code-secret", "state": "oauth-state-secret"},
    )
    await client.get("/api/v1/tracks/search", params={"q": "private search words"})
    logged = caplog.text
    for secret in (password, cookie, "provider-code-secret", "oauth-state-secret"):
        assert secret not in logged
    # Access lines carry route templates, never query strings.
    assert "private search words" not in logged
    assert "GET /tracks/search 200" in logged or "/api/v1/tracks/search" in logged
