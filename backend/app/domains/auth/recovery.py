"""Password reset and e-mail address verification (Milestone 7, ADR-020; spec §12.1).

- Links carry a random 256-bit token; only its SHA-256 is stored (`account_tokens`).
- Tokens are single use, expire (reset: PASSWORD_RESET_MINUTES; verification:
  EMAIL_VERIFICATION_HOURS), and issuing a new one invalidates the older unused ones.
- Requesting a reset never reveals whether an account exists: the API answers the same way and
  only sends mail to real accounts.
- A reset signs out every session (whoever had the old password loses access) and counts as
  proof of the address.
"""

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.mail import Email, Mailer
from app.domains.auth import passwords
from app.domains.auth.service import AuthError, WeakPasswordError, hash_token
from app.domains.users.models import AccountToken, User, UserSession

logger = logging.getLogger(__name__)

PASSWORD_RESET = "password_reset"  # noqa: S105 - a token purpose, not a secret
EMAIL_VERIFICATION = "email_verification"


class InvalidTokenError(AuthError):
    def __init__(self) -> None:
        super().__init__("This link is invalid or has expired; request a new one")


class AlreadyVerifiedError(AuthError):
    def __init__(self) -> None:
        super().__init__("Your e-mail address is already verified")


def _link(path: str, token: str) -> str:
    base = get_settings().app_public_url.rstrip("/")
    return f"{base}{path}?{urlencode({'token': token})}"


def reset_email(to: str, token: str, minutes: int) -> Email:
    return Email(
        to=to,
        subject="Reset your SONIQUEO password",
        kind=PASSWORD_RESET,
        text=(
            "Someone asked to reset the password of the SONIQUEO account for this address.\n\n"
            f"Choose a new password here (the link works once, for {minutes} minutes):\n"
            f"{_link('/reset-password', token)}\n\n"
            "If it wasn't you, ignore this message: your password stays the same.\n"
        ),
    )


def verification_email(to: str, token: str, hours: int) -> Email:
    return Email(
        to=to,
        subject="Confirm your e-mail address for SONIQUEO",
        kind=EMAIL_VERIFICATION,
        text=(
            "Confirm that this is your address, so you can always recover your SONIQUEO "
            "account:\n"
            f"{_link('/verify-email', token)}\n\n"
            f"The link works once, for {hours} hours. If you did not create a SONIQUEO account, "
            "ignore this message.\n"
        ),
    )


class RecoveryService:
    def __init__(self, session: AsyncSession, mailer: Mailer) -> None:
        self.session = session
        self.mailer = mailer

    async def _issue(self, user: User, purpose: str, lifetime: timedelta) -> str:
        now = datetime.now(UTC)
        # Older unused links of the same kind stop working.
        await self.session.execute(
            update(AccountToken)
            .where(
                AccountToken.user_id == user.id,
                AccountToken.purpose == purpose,
                AccountToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        token = secrets.token_urlsafe(32)
        self.session.add(
            AccountToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=hash_token(token),
                email=user.email,
                expires_at=now + lifetime,
            )
        )
        await self.session.flush()
        return token

    async def _redeem(self, token: str, purpose: str) -> tuple[AccountToken, User]:
        """Mark a valid token used (atomically: a token can be redeemed exactly once)."""
        now = datetime.now(UTC)
        record = await self.session.scalar(
            update(AccountToken)
            .where(
                AccountToken.token_hash == hash_token(token),
                AccountToken.purpose == purpose,
                AccountToken.used_at.is_(None),
                AccountToken.expires_at > now,
            )
            .values(used_at=now)
            .returning(AccountToken)
        )
        if record is None:
            raise InvalidTokenError()
        user = await self.session.get(User, record.user_id)
        if user is None or user.status != "active" or user.email != record.email:
            # The address changed since the link was sent: the link no longer proves anything.
            await self.session.rollback()
            raise InvalidTokenError()
        return record, user

    async def request_password_reset(self, email: str) -> None:
        """Send a reset link if an active account uses this address; silent otherwise."""
        user = await self.session.scalar(
            select(User).where(User.email == email, User.status == "active")
        )
        if user is None:
            logger.info("password reset requested for an unknown address")
            return
        minutes = get_settings().password_reset_minutes
        token = await self._issue(user, PASSWORD_RESET, timedelta(minutes=minutes))
        # Queue first, commit after: if mail cannot be queued, no unusable token is left behind.
        await self.mailer.send(reset_email(user.email, token, minutes))
        await self.session.commit()
        logger.info("password reset link sent user=%s", user.id)

    async def reset_password(self, token: str, new_password: str) -> uuid.UUID:
        record, user = await self._redeem(token, PASSWORD_RESET)
        problem = passwords.password_problem(new_password, user.email)
        if problem is not None:
            await self.session.rollback()  # the link stays usable for a better password
            raise WeakPasswordError(problem)
        now = datetime.now(UTC)
        user.password_hash = await passwords.hash_password_async(new_password)
        if user.email_verified_at is None:
            user.email_verified_at = now  # the reset link proved the address
        await self.session.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await self.session.commit()
        logger.info("password reset user=%s", user.id)
        return record.user_id

    async def send_verification(self, user: User) -> None:
        if user.email_verified_at is not None:
            raise AlreadyVerifiedError()
        hours = get_settings().email_verification_hours
        token = await self._issue(user, EMAIL_VERIFICATION, timedelta(hours=hours))
        await self.mailer.send(verification_email(user.email, token, hours))
        await self.session.commit()
        logger.info("verification link sent user=%s", user.id)

    async def verify_email(self, token: str) -> None:
        _, user = await self._redeem(token, EMAIL_VERIFICATION)
        if user.email_verified_at is None:
            user.email_verified_at = datetime.now(UTC)
        await self.session.commit()
        logger.info("e-mail verified user=%s", user.id)
