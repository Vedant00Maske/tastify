"""Request-level authentication: the session cookie, the current user and the Origin check.

CSRF protection has two layers: the session cookie is SameSite=Lax (browsers do not send it on
cross-site POST, PUT, PATCH or DELETE), and every state-changing request that carries an `Origin`
header must come from an allowed origin (`OriginCheckMiddleware`).
"""

from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings
from app.core.database import get_db_session
from app.domains.auth.service import AuthService
from app.domains.users.models import User

SESSION_COOKIE = "tastify_session"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def set_session_cookie(response: Response, token: str, expires_at: datetime) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        expires=expires_at,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


async def optional_user(
    request: Request, session: Annotated[AsyncSession, Depends(get_db_session)]
) -> User | None:
    return await AuthService(session).user_for_token(session_token(request))


async def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


class OriginCheckMiddleware:
    """Rejects state-changing requests whose Origin header is present but not allowed (403).

    Requests without Origin (server-to-server clients, tests) pass: browsers always send Origin on
    the cross-site requests that CSRF relies on."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in UNSAFE_METHODS:
            origin = next(
                (v.decode("latin-1") for k, v in scope["headers"] if k == b"origin"), None
            )
            if origin is not None and origin not in get_settings().allowed_origins:
                response = Response(
                    '{"detail":"Origin not allowed"}',
                    status_code=status.HTTP_403_FORBIDDEN,
                    media_type="application/json",
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
