"""Authentication, sessions, account management and data export (Milestone 4, ADR-017)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.dependencies import SESSION_COOKIE
from app.domains.auth.service import hash_token
from app.domains.users.models import UserSession

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery"  # noqa: S105 - test credential


def account(**overrides: object) -> dict[str, object]:
    return {
        "email": f"Person-{uuid.uuid4().hex[:10]}@Example.com",
        "password": PASSWORD,
        "display_name": "  Robin  ",
        "accept_terms": True,
        **overrides,
    }


async def new_client() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_register_signs_in_with_an_http_only_cookie(
    client: AsyncClient, session: AsyncSession
) -> None:
    data = account()
    response = await client.post("/api/v1/auth/register", json=data)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == str(data["email"]).lower()
    assert body["display_name"] == "Robin"
    assert body["onboarding_completed"] is False
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in cookie
    assert "samesite=lax" in cookie.lower()
    token = response.cookies[SESSION_COOKIE]
    stored = await session.scalar(select(UserSession.token_hash))
    assert stored == hash_token(token)  # only the hash is stored
    assert stored != token
    me = await client.get("/api/v1/users/me")
    assert me.json()["id"] == body["id"]


@pytest.mark.parametrize(
    ("overrides", "status_code", "fragment"),
    [
        ({"accept_terms": False}, 422, "terms"),
        ({"password": "short"}, 422, "at least 10"),
        ({"email": "not-an-email"}, 422, "e-mail"),
    ],
)
async def test_registration_rules(
    client: AsyncClient,
    session: AsyncSession,
    overrides: dict[str, object],
    status_code: int,
    fragment: str,
) -> None:
    response = await client.post("/api/v1/auth/register", json=account(**overrides))
    assert response.status_code == status_code
    assert fragment in response.text


async def test_duplicate_email_is_a_conflict_case_insensitively(
    client: AsyncClient, session: AsyncSession
) -> None:
    data = account(email="Same@Example.com")
    assert (await client.post("/api/v1/auth/register", json=data)).status_code == 201
    again = await client.post("/api/v1/auth/register", json=account(email="same@example.COM"))
    assert again.status_code == 409


async def test_login_logout_and_wrong_password(client: AsyncClient, session: AsyncSession) -> None:
    data = account()
    await client.post("/api/v1/auth/register", json=data)
    await client.post("/api/v1/auth/logout")
    assert (await client.get("/api/v1/users/me")).status_code == 401
    wrong = await client.post(
        "/api/v1/auth/login", json={"email": data["email"], "password": "wrong password!"}
    )
    assert wrong.status_code == 401
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]  # no account enumeration
    ok = await client.post(
        "/api/v1/auth/login", json={"email": str(data["email"]).upper(), "password": PASSWORD}
    )
    assert ok.status_code == 200
    assert (await client.get("/api/v1/users/me")).status_code == 200
    revoked = await session.scalar(
        select(func.count()).select_from(UserSession).where(UserSession.revoked_at.is_not(None))
    )
    assert revoked == 1


async def test_login_attempts_are_rate_limited(client: AsyncClient, session: AsyncSession) -> None:
    data = account()
    await client.post("/api/v1/auth/register", json=data)
    statuses = [
        (
            await client.post(
                "/api/v1/auth/login", json={"email": data["email"], "password": "wrong password!"}
            )
        ).status_code
        for _ in range(11)
    ]
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


async def test_state_changes_from_foreign_origins_are_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    foreign = await client.post(
        "/api/v1/auth/register", json=account(), headers={"Origin": "https://evil.example"}
    )
    assert foreign.status_code == 403
    allowed = await client.post(
        "/api/v1/auth/register", json=account(), headers={"Origin": "http://localhost:3000"}
    )
    assert allowed.status_code == 201


async def test_password_change_signs_out_other_sessions(
    client: AsyncClient, session: AsyncSession
) -> None:
    data = account()
    await client.post("/api/v1/auth/register", json=data)
    async with await new_client() as other:
        await other.post("/api/v1/auth/login", json={"email": data["email"], "password": PASSWORD})
        assert (await other.get("/api/v1/users/me")).status_code == 200
        wrong = await client.post(
            "/api/v1/auth/password",
            json={"current_password": "nope nope nope", "new_password": "another long pass"},
        )
        assert wrong.status_code == 401
        changed = await client.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": "another long pass"},
        )
        assert changed.status_code == 204
        assert (await other.get("/api/v1/users/me")).status_code == 401
        assert (await client.get("/api/v1/users/me")).status_code == 200


async def test_profile_update_onboarding_flag_and_export(
    client: AsyncClient, session: AsyncSession
) -> None:
    await client.post("/api/v1/auth/register", json=account())
    updated = await client.patch(
        "/api/v1/users/me", json={"display_name": "Sam", "onboarding_completed": True}
    )
    assert updated.json()["display_name"] == "Sam"
    assert updated.json()["onboarding_completed"] is True
    export = await client.get("/api/v1/users/me/export")
    assert export.status_code == 200
    assert "attachment" in export.headers["content-disposition"]
    body = export.json()
    assert body["account"]["display_name"] == "Sam"
    assert "password_hash" not in export.text
    assert set(body) >= {"account", "preferences", "interactions", "playlists", "sessions"}


async def test_account_deletion_removes_everything(
    client: AsyncClient, session: AsyncSession
) -> None:
    await client.post("/api/v1/auth/register", json=account())
    refused = await client.request(
        "DELETE", "/api/v1/users/me", json={"password": "wrong password!"}
    )
    assert refused.status_code == 401
    deleted = await client.request("DELETE", "/api/v1/users/me", json={"password": PASSWORD})
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/users/me")).status_code == 401
    for table in ("users", "user_sessions"):
        count = await session.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
        assert count == 0
