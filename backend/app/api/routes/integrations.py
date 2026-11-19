"""Music platform integrations (Milestone 5; API_SPEC.md, ADR-018).

Every route acts on the signed-in user's own connections and playlists. Provider failures map
to specific statuses (502 provider failed, 429 rate limit or quota, 409 reconnect needed,
503 not configured here) and never affect the rest of the API.
"""

import uuid
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.redis import get_redis
from app.domains.auth.dependencies import CurrentUser, optional_user
from app.domains.integrations.providers.base import (
    IntegrationError,
    InvalidCredentialsError,
    MusicProvider,
    NotSupportedError,
    ProviderAuthError,
    ProviderNotConfiguredError,
    ProviderRateLimitedError,
    QuotaExceededError,
)
from app.domains.integrations.schemas import (
    AuthorizeOut,
    ExportIn,
    ExportList,
    ExportOut,
    ImportIn,
    ImportOut,
    ProviderList,
    RecordingSearchOut,
    TokenConnectIn,
)
from app.domains.integrations.service import (
    ConsentRequiredError,
    IntegrationService,
    NotConnectedError,
    OAuthStateError,
    UnknownProviderError,
    default_providers,
)
from app.domains.integrations.tokens import TokenKeyMissingError
from app.domains.playlists.service import PlaylistNotFoundError
from app.domains.users.models import User

router = APIRouter(tags=["integrations"])


def get_providers() -> dict[str, MusicProvider]:
    """The provider adapters (replaced by fakes in tests)."""
    return default_providers()


async def get_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    providers: Annotated[dict[str, MusicProvider], Depends(get_providers)],
) -> IntegrationService:
    return IntegrationService(session, redis, providers)


Service = Annotated[IntegrationService, Depends(get_service)]


def integration_error(error: Exception) -> HTTPException:
    def problem(code: int, kind: str, headers: dict[str, str] | None = None) -> HTTPException:
        return HTTPException(code, detail={"message": str(error), "code": kind}, headers=headers)

    match error:
        case UnknownProviderError() | PlaylistNotFoundError():
            return problem(status.HTTP_404_NOT_FOUND, "not_found")
        case NotSupportedError():
            return problem(status.HTTP_400_BAD_REQUEST, "not_supported")
        case ProviderNotConfiguredError() | TokenKeyMissingError():
            return HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "message": "This integration is not configured on this server.",
                    "code": "not_configured",
                },
            )
        case NotConnectedError():
            return problem(status.HTTP_409_CONFLICT, "not_connected")
        case ProviderAuthError():
            return problem(status.HTTP_409_CONFLICT, "reauth_required")
        case ConsentRequiredError():
            return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, "consent_required")
        case InvalidCredentialsError():
            return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_credentials")
        case OAuthStateError():
            return problem(status.HTTP_400_BAD_REQUEST, "invalid_state")
        case ProviderRateLimitedError():
            retry = str(int(error.retry_after)) if error.retry_after else "60"
            return problem(
                status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", {"Retry-After": retry}
            )
        case QuotaExceededError():
            return problem(status.HTTP_429_TOO_MANY_REQUESTS, "quota_exceeded")
    return problem(status.HTTP_502_BAD_GATEWAY, "provider_failed")


HANDLED = (IntegrationError, PlaylistNotFoundError, TokenKeyMissingError)


@router.get("/integrations")
async def list_integrations(user: CurrentUser, service: Service) -> ProviderList:
    """Every provider, whether it is available here, and the user's connection to it."""
    return await service.overview(user.id)


@router.post("/integrations/{provider}/connect")
async def connect_with_token(
    provider: str, data: TokenConnectIn, user: CurrentUser, service: Service
) -> ProviderList:
    """Connect a provider that uses a personal token (ListenBrainz)."""
    try:
        return await service.connect_token(user.id, provider, data.token)
    except HANDLED as error:
        raise integration_error(error) from error


@router.get("/integrations/{provider}/authorize")
async def authorize(provider: str, user: CurrentUser, service: Service) -> AuthorizeOut:
    """The provider's sign-in page (OAuth with PKCE); the browser is sent there."""
    try:
        return AuthorizeOut(url=await service.authorize(user.id, provider))
    except HANDLED as error:
        raise integration_error(error) from error


@router.get("/integrations/{provider}/callback", include_in_schema=False)
async def oauth_callback(
    provider: str,
    service: Service,
    user: Annotated[User | None, Depends(optional_user)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Where the provider sends the browser back; finishes connecting, then opens Settings."""
    app = get_settings().app_public_url.rstrip("/")
    if user is None:
        return RedirectResponse(f"{app}/login", status.HTTP_303_SEE_OTHER)

    def back(result: str, reason: str | None = None) -> RedirectResponse:
        query = {"integration": provider, "status": result}
        if reason:
            query["reason"] = reason
        return RedirectResponse(
            f"{app}/settings?{urlencode(query)}#connections", status.HTTP_303_SEE_OTHER
        )

    if error or not code or not state:
        return back("cancelled" if error == "access_denied" else "error", error or "missing_code")
    try:
        await service.complete_oauth(user.id, provider, code, state)
    except HANDLED as failure:
        detail = integration_error(failure).detail
        kind = detail.get("code") if isinstance(detail, dict) else None
        return back("error", str(kind or "failed"))
    return back("connected")


@router.delete("/integrations/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    provider: str,
    user: CurrentUser,
    service: Service,
    delete_imported: Annotated[
        bool, Query(description="Also delete the history imported from this provider")
    ] = False,
) -> None:
    """Forget the provider's tokens (and ask the provider to revoke them where it can)."""
    try:
        await service.disconnect(user.id, provider, delete_imported)
    except HANDLED as error:
        raise integration_error(error) from error


@router.post("/integrations/{provider}/import")
async def import_history(
    provider: str, data: ImportIn, user: CurrentUser, service: Service
) -> ImportOut:
    """Copy listening history or library data into TASTIFY (incremental, idempotent)."""
    try:
        return await service.import_history(user.id, provider, data.consent)
    except HANDLED as error:
        raise integration_error(error) from error


@router.get("/integrations/imports")
async def list_imports(user: CurrentUser, service: Service) -> list[ImportOut]:
    return await service.imports(user.id)


@router.get("/integrations/musicbrainz/search")
async def search_musicbrainz(
    user: CurrentUser,
    service: Service,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> RecordingSearchOut:
    """Recordings on MusicBrainz, marked when the TASTIFY catalogue has them."""
    try:
        return await service.search_musicbrainz(q, limit)
    except HANDLED as error:
        raise integration_error(error) from error


@router.post("/playlists/{playlist_id}/export")
async def export_playlist(
    playlist_id: uuid.UUID, data: ExportIn, user: CurrentUser, service: Service
) -> ExportOut:
    """Create or update the playlist on a connected provider (retry-safe)."""
    try:
        return await service.export_playlist(user.id, playlist_id, data.provider)
    except HANDLED as error:
        raise integration_error(error) from error


@router.get("/playlists/{playlist_id}/exports")
async def list_exports(playlist_id: uuid.UUID, user: CurrentUser, service: Service) -> ExportList:
    try:
        return ExportList(exports=await service.exports(user.id, playlist_id))
    except HANDLED as error:
        raise integration_error(error) from error
