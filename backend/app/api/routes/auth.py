"""Authentication endpoints (Milestone 4; API_SPEC.md, ADR-017)."""

import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.redis import get_redis
from app.domains.auth import rate_limit
from app.domains.auth.dependencies import (
    CurrentUser,
    clear_session_cookie,
    session_token,
    set_session_cookie,
)
from app.domains.auth.schemas import LoginIn, MeOut, PasswordChangeIn, RegisterIn
from app.domains.auth.service import (
    AuthError,
    AuthService,
    EmailTakenError,
    InvalidCredentialsError,
    me,
)

router = APIRouter(prefix="/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_db_session)]
RedisClient = Annotated[Redis, Depends(get_redis)]


def _trusted(peer: str, proxies: list[str]) -> bool:
    """Whether `peer` is one of the configured proxies (addresses or networks, e.g. a Docker
    network range)."""
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for proxy in proxies:
        try:
            if address in ipaddress.ip_network(proxy, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request) -> str:
    """The caller's address; X-Forwarded-For is trusted only from configured proxies (the Next.js
    server in front of the API)."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _trusted(peer, get_settings().trusted_proxies):
        return forwarded.split(",")[0].strip()
    return peer


def _http_error(error: AuthError) -> HTTPException:
    if isinstance(error, EmailTakenError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, InvalidCredentialsError):
        return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(error))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


def _too_many(error: rate_limit.RateLimitedError) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail=str(error),
        headers={"Retry-After": str(error.retry_after)},
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    request: Request, response: Response, session: Session, redis: RedisClient, data: RegisterIn
) -> MeOut:
    """Create an account and sign in (session cookie)."""
    try:
        await rate_limit.hit(redis, rate_limit.REGISTER_PER_CLIENT, client_ip(request))
        user, new_session = await AuthService(session).register(
            data, request.headers.get("user-agent")
        )
    except rate_limit.RateLimitedError as error:
        raise _too_many(error) from error
    except AuthError as error:
        raise _http_error(error) from error
    set_session_cookie(response, new_session.token, new_session.expires_at)
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
        raise _too_many(error) from error
    except AuthError as error:
        raise _http_error(error) from error
    await rate_limit.reset(redis, rate_limit.LOGIN_PER_ACCOUNT, data.email)
    set_session_cookie(response, new_session.token, new_session.expires_at)
    return me(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: Session) -> None:
    await AuthService(session).logout(session_token(request))
    clear_session_cookie(response)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
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
