"""Authentication endpoints (Milestone 4; API_SPEC.md, ADR-017)."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.limits import client_ip, limit, too_many
from app.core.database import SessionFactory, get_db_session
from app.core.mail import DisabledMailer, Mailer, MailUnavailableError, get_mailer
from app.core.redis import get_redis
from app.domains.auth import rate_limit
from app.domains.auth.dependencies import (
    CurrentUser,
    clear_session_cookie,
    session_token,
    set_session_cookie,
)
from app.domains.auth.recovery import AlreadyVerifiedError, InvalidTokenError, RecoveryService
from app.domains.auth.schemas import (
    EmailVerifyIn,
    LoginIn,
    MeOut,
    PasswordChangeIn,
    PasswordResetIn,
    PasswordResetRequestIn,
    RegisterIn,
)
from app.domains.auth.service import (
    AuthError,
    AuthService,
    EmailTakenError,
    InvalidCredentialsError,
    me,
)
from app.domains.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_db_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]


def _http_error(error: AuthError) -> HTTPException:
    if isinstance(error, EmailTakenError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, InvalidCredentialsError):
        return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(error))
    if isinstance(error, InvalidTokenError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(error))
    if isinstance(error, AlreadyVerifiedError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(error))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


def _mail_unavailable() -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "email_unavailable", "message": "E-mail cannot be sent right now"},
    )


async def _send_verification(user_id: uuid.UUID, mailer: Mailer) -> None:
    """After registration, outside the request: a mail problem must not fail the sign-up."""
    async with SessionFactory() as session:
        user = await session.get(User, user_id)
        if user is None:
            return
        try:
            await RecoveryService(session, mailer).send_verification(user)
        except (MailUnavailableError, AlreadyVerifiedError):
            logger.info("verification e-mail not sent user=%s", user_id)


async def _send_reset(email: str, mailer: Mailer) -> None:
    """Outside the request, so the response time does not reveal whether the account exists."""
    async with SessionFactory() as session:
        try:
            await RecoveryService(session, mailer).request_password_reset(email)
        except MailUnavailableError:
            logger.warning("password reset e-mail could not be queued")


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    response: Response,
    session: Session,
    redis: RedisClient,
    mailer: MailerDep,
    background: BackgroundTasks,
    data: RegisterIn,
) -> MeOut:
    """Create an account and sign in (session cookie); a verification link is e-mailed."""
    try:
        await rate_limit.hit(redis, rate_limit.REGISTER_PER_CLIENT, client_ip(request))
        user, new_session = await AuthService(session).register(
            data, request.headers.get("user-agent")
        )
    except rate_limit.RateLimitedError as error:
        raise too_many(error) from error
    except AuthError as error:
        raise _http_error(error) from error
    set_session_cookie(response, new_session.token, new_session.expires_at)
    background.add_task(_send_verification, user.id, mailer)
    return me(user)


@router.post("/login")
async def login(
    request: Request, response: Response, session: Session, redis: RedisClient, data: LoginIn
) -> MeOut:
    try:
        await rate_limit.hit(redis, rate_limit.LOGIN_PER_CLIENT, client_ip(request))
        await rate_limit.hit(redis, rate_limit.LOGIN_PER_ACCOUNT, data.email)
        user, new_session = await AuthService(session).login(
            data.email, data.password, request.headers.get("user-agent")
        )
    except rate_limit.RateLimitedError as error:
        raise too_many(error) from error
    except AuthError as error:
        raise _http_error(error) from error
    await rate_limit.reset(redis, rate_limit.LOGIN_PER_ACCOUNT, data.email)
    set_session_cookie(response, new_session.token, new_session.expires_at)
    return me(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: Session) -> None:
    await AuthService(session).logout(session_token(request))
    clear_session_cookie(response)


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[limit(rate_limit.PASSWORD_CONFIRM_PER_USER, per="user")],
)
async def change_password(
    request: Request, session: Session, user: CurrentUser, data: PasswordChangeIn
) -> None:
    """Change the password; every other session is signed out."""
    try:
        await AuthService(session).change_password(
            user, data.current_password, data.new_password, session_token(request)
        )
    except InvalidCredentialsError as error:
        # Signed in, but the confirmation failed: 403, not 401 (the session itself is valid,
        # and clients treat 401 as "signed out").
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="current password is wrong"
        ) from error
    except AuthError as error:
        raise _http_error(error) from error


@router.post(
    "/password/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[limit(rate_limit.RESET_REQUEST_PER_CLIENT)],
)
async def forgot_password(
    redis: RedisClient,
    mailer: MailerDep,
    background: BackgroundTasks,
    data: PasswordResetRequestIn,
) -> None:
    """E-mail a reset link if an account uses this address. The answer is the same either way,
    so it cannot be used to find out who has an account."""
    if isinstance(mailer, DisabledMailer):
        raise _mail_unavailable()
    try:
        await rate_limit.hit(redis, rate_limit.RESET_REQUEST_PER_ACCOUNT, data.email)
    except rate_limit.RateLimitedError:
        return  # silently: answering 429 here would confirm that the address was used
    background.add_task(_send_reset, data.email, mailer)


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[limit(rate_limit.TOKEN_SUBMIT_PER_CLIENT)],
)
async def reset_password(
    response: Response, session: Session, mailer: MailerDep, data: PasswordResetIn
) -> None:
    """Set a new password with a reset link's token. Every session is signed out; sign in with
    the new password."""
    try:
        await RecoveryService(session, mailer).reset_password(data.token, data.new_password)
    except AuthError as error:
        raise _http_error(error) from error
    clear_session_cookie(response)


@router.post(
    "/email/verify",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[limit(rate_limit.TOKEN_SUBMIT_PER_CLIENT)],
)
async def verify_email(session: Session, mailer: MailerDep, data: EmailVerifyIn) -> None:
    """Confirm the address with a verification link's token (signed in or not)."""
    try:
        await RecoveryService(session, mailer).verify_email(data.token)
    except AuthError as error:
        raise _http_error(error) from error


@router.post(
    "/email/verification",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[limit(rate_limit.VERIFICATION_PER_USER, per="user")],
)
async def resend_verification(session: Session, mailer: MailerDep, user: CurrentUser) -> None:
    """Send a new verification link to the signed-in user's address."""
    try:
        await RecoveryService(session, mailer).send_verification(user)
    except MailUnavailableError as error:
        raise _mail_unavailable() from error
    except AuthError as error:
        raise _http_error(error) from error
