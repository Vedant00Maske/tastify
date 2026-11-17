"""Registration, login, sessions, password changes and account deletion (spec §12.1, ADR-017).

Sessions are server-side: the browser holds a random 256-bit token in an HttpOnly, SameSite=Lax
cookie, the database stores only its SHA-256. A session expires `SESSION_DAYS` after its last use
(sliding), and logout, password changes and account deletion revoke sessions immediately.
"""

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth import passwords
from app.domains.auth.schemas import MeOut, RegisterIn
from app.domains.users.models import User, UserSession

logger = logging.getLogger(__name__)

SESSION_DAYS = 30
# A session's expiry is pushed forward at most once per this interval (avoids a write per request).
SESSION_REFRESH = timedelta(hours=1)


class AuthError(Exception):
    """Base class for errors the API maps to HTTP responses."""


class EmailTakenError(AuthError):
    def __init__(self) -> None:
        super().__init__("An account with this e-mail already exists")


class InvalidCredentialsError(AuthError):
    def __init__(self) -> None:
        super().__init__("E-mail or password is incorrect")


class WeakPasswordError(AuthError):
    def __init__(self, problem: str) -> None:
        super().__init__(f"Password {problem}")


class TermsNotAcceptedError(AuthError):
    def __init__(self) -> None:
        super().__init__("Accept the terms and privacy notice to create an account")


class NotAuthenticatedError(AuthError):
    def __init__(self) -> None:
        super().__init__("Not signed in")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def me(user: User) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
        onboarding_completed=user.onboarding_completed_at is not None,
    )


@dataclass(frozen=True)
class NewSession:
    token: str
    expires_at: datetime


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _open_session(self, user: User, user_agent: str | None) -> NewSession:
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        expires = now + timedelta(days=SESSION_DAYS)
        self.session.add(
            UserSession(
                user_id=user.id,
                token_hash=hash_token(token),
                expires_at=expires,
                last_seen_at=now,
                user_agent=(user_agent or "")[:256] or None,
            )
        )
        user.last_login_at = now
        await self.session.flush()
        return NewSession(token, expires)

    async def register(self, data: RegisterIn, user_agent: str | None) -> tuple[User, NewSession]:
        if not data.accept_terms:
            raise TermsNotAcceptedError()
        problem = passwords.password_problem(data.password, data.email)
        if problem is not None:
            raise WeakPasswordError(problem)
        existing = await self.session.scalar(select(User.id).where(User.email == data.email))
        if existing is not None:
            raise EmailTakenError()
        user = User(
            email=data.email,
            password_hash=passwords.hash_password(data.password),
            display_name=data.display_name,
            terms_accepted_at=datetime.now(UTC),
        )
        self.session.add(user)
        try:
            await self.session.flush()
        except IntegrityError as error:  # a concurrent registration with the same e-mail
            await self.session.rollback()
            raise EmailTakenError() from error
        await self.session.refresh(user)
        new_session = await self._open_session(user, user_agent)
        await self.session.commit()
        logger.info("user registered user=%s", user.id)
        return user, new_session

    async def login(
        self, email: str, password: str, user_agent: str | None
    ) -> tuple[User, NewSession]:
        user = await self.session.scalar(
            select(User).where(User.email == email, User.status == "active")
        )
        if user is None:
            passwords.verify_password(passwords.DUMMY_HASH, password)
            raise InvalidCredentialsError()
        if not passwords.verify_password(user.password_hash, password):
            raise InvalidCredentialsError()
        if passwords.needs_rehash(user.password_hash):
            user.password_hash = passwords.hash_password(password)
        new_session = await self._open_session(user, user_agent)
        await self.session.commit()
        logger.info("user logged in user=%s", user.id)
        return user, new_session

    async def user_for_token(self, token: str | None) -> User | None:
        """The active user of a valid, unexpired, unrevoked session token (sliding expiry)."""
        if not token:
            return None
        now = datetime.now(UTC)
        row = (
            await self.session.execute(
                select(UserSession, User)
                .join(User, User.id == UserSession.user_id)
                .where(
                    UserSession.token_hash == hash_token(token),
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                    User.status == "active",
                )
            )
        ).first()
        if row is None:
            return None
        user_session, user = row
        if now - user_session.last_seen_at > SESSION_REFRESH:
            user_session.last_seen_at = now
            user_session.expires_at = now + timedelta(days=SESSION_DAYS)
            await self.session.commit()
        return user

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        await self.session.execute(
            update(UserSession)
            .where(UserSession.token_hash == hash_token(token), UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await self.session.commit()

    async def change_password(
        self, user: User, current: str, new: str, keep_token: str | None
    ) -> None:
        """Change the password and sign out every other session."""
        if not passwords.verify_password(user.password_hash, current):
            raise InvalidCredentialsError()
        problem = passwords.password_problem(new, user.email)
        if problem is not None:
            raise WeakPasswordError(problem)
        user.password_hash = passwords.hash_password(new)
        statement = update(UserSession).where(
            UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
        )
        if keep_token:
            statement = statement.where(UserSession.token_hash != hash_token(keep_token))
        await self.session.execute(statement.values(revoked_at=datetime.now(UTC)))
        await self.session.commit()
        logger.info("password changed user=%s", user.id)

    async def delete_account(self, user: User, password: str) -> None:
        """Delete the user and everything that belongs to them (cascades: events, preferences,
        profile, playlists, sessions). Spec §12.4, account deletion."""
        if not passwords.verify_password(user.password_hash, password):
            raise InvalidCredentialsError()
        user_id: uuid.UUID = user.id
        await self.session.execute(delete(User).where(User.id == user_id))
        await self.session.commit()
        logger.info("account deleted user=%s", user_id)
