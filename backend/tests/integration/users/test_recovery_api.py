"""Password reset and e-mail verification (Milestone 7, ADR-020)."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mail import DisabledMailer, Email, get_mailer
from app.domains.users.models import AccountToken, User, UserSession

pytestmark = pytest.mark.integration

PASSWORD = "correct horse battery"  # noqa: S105 - test credential
NEW_PASSWORD = "a brand new passphrase"  # noqa: S105 - test credential


class RecordingMailer:
    def __init__(self) -> None:
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        self.sent.append(email)

    def token(self, kind: str) -> str:
        message = next(m for m in reversed(self.sent) if m.kind == kind)
        match = re.search(r"\?token=([A-Za-z0-9_-]+)", message.text)
        assert match, message.text
        return match.group(1)


@pytest.fixture
async def mailer(client: AsyncClient) -> RecordingMailer:
    from app.main import app

    recorder = RecordingMailer()
    app.dependency_overrides[get_mailer] = lambda: recorder
    return recorder


async def register(client: AsyncClient, email: str | None = None) -> str:
    email = email or f"reader-{uuid.uuid4().hex[:10]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "accept_terms": True},
    )
    assert response.status_code == 201, response.text
    return email


async def test_registration_sends_a_verification_link_that_verifies_once(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await register(client)
    assert (await client.get("/api/v1/users/me")).json()["email_verified"] is False
    assert [m.kind for m in mailer.sent] == ["email_verification"]
    message = mailer.sent[0]
    assert message.to == email
    assert "/verify-email?token=" in message.text
    token = mailer.token("email_verification")
    stored = await session.scalar(select(AccountToken.token_hash))
    assert stored is not None
    assert token not in stored  # only the hash is stored

    assert (
        await client.post("/api/v1/auth/email/verify", json={"token": token})
    ).status_code == 204
    assert (await client.get("/api/v1/users/me")).json()["email_verified"] is True
    again = await client.post("/api/v1/auth/email/verify", json={"token": token})
    assert again.status_code == 400  # single use
    resend = await client.post("/api/v1/auth/email/verification")
    assert resend.status_code == 409  # already verified
    export = (await client.get("/api/v1/users/me/export")).json()
    assert export["account"]["email_verified_at"] is not None


async def test_a_new_verification_link_replaces_the_old_one(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer
) -> None:
    await register(client)
    first = mailer.token("email_verification")
    assert (await client.post("/api/v1/auth/email/verification")).status_code == 202
    second = mailer.token("email_verification")
    assert first != second
    old = await client.post("/api/v1/auth/email/verify", json={"token": first})
    assert old.status_code == 400
    assert (
        await client.post("/api/v1/auth/email/verify", json={"token": second})
    ).status_code == 204


async def test_password_reset_signs_out_everywhere_and_sets_the_new_password(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await register(client)
    forgot = await client.post("/api/v1/auth/password/forgot", json={"email": email.upper()})
    assert forgot.status_code == 202
    token = mailer.token("password_reset")
    assert "/reset-password?token=" in mailer.sent[-1].text

    weak = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": "short"}
    )
    assert weak.status_code == 422  # the link stays usable for a valid password
    reset = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert reset.status_code == 204
    # Every session, including this browser's, was revoked.
    assert (await client.get("/api/v1/users/me")).status_code == 401
    open_sessions = await session.scalar(
        select(UserSession.id).where(UserSession.revoked_at.is_(None))
    )
    assert open_sessions is None
    reused = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert reused.status_code == 400

    old = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert old.status_code == 401
    new = await client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})
    assert new.status_code == 200
    assert new.json()["email_verified"] is True  # the reset link proved the address


async def test_reset_requests_do_not_reveal_accounts(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    unknown = await client.post(
        "/api/v1/auth/password/forgot", json={"email": "nobody-here@example.com"}
    )
    assert unknown.status_code == 202
    assert mailer.sent == []
    email = await register(client)
    mailer.sent.clear()
    for _ in range(5):  # past the per-address limit: still 202, but no more mail
        response = await client.post("/api/v1/auth/password/forgot", json={"email": email})
        assert response.status_code == 202
    assert len(mailer.sent) == 3


async def test_expired_reset_links_are_refused(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await register(client)
    await client.post("/api/v1/auth/password/forgot", json={"email": email})
    token = mailer.token("password_reset")
    await session.execute(
        update(AccountToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await session.commit()
    response = await client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert response.status_code == 400


async def test_links_sent_to_an_old_address_do_not_count(
    client: AsyncClient, session: AsyncSession, mailer: RecordingMailer
) -> None:
    email = await register(client)
    token = mailer.token("email_verification")
    await session.execute(update(User).where(User.email == email).values(email=f"changed-{email}"))
    await session.commit()
    response = await client.post("/api/v1/auth/email/verify", json={"token": token})
    assert response.status_code == 400


async def test_without_e_mail_the_features_say_so(client: AsyncClient) -> None:
    from app.main import app

    app.dependency_overrides[get_mailer] = DisabledMailer
    email = await register(client)  # registration still works
    forgot = await client.post("/api/v1/auth/password/forgot", json={"email": email})
    assert forgot.status_code == 503
    assert forgot.json()["detail"]["code"] == "email_unavailable"
    resend = await client.post("/api/v1/auth/email/verification")
    assert resend.status_code == 503


async def test_token_endpoints_validate_and_limit(
    client: AsyncClient, mailer: RecordingMailer
) -> None:
    short = await client.post("/api/v1/auth/email/verify", json={"token": "x"})
    assert short.status_code == 422
    statuses = [
        (await client.post("/api/v1/auth/email/verify", json={"token": "y" * 43})).status_code
        for _ in range(30)
    ]
    # The malformed request above counted too: 30 attempts per hour per client.
    assert statuses[:29] == [400] * 29
    assert statuses[29] == 429
