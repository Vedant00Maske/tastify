"""The current user's account, preferences, taste profile and data (Milestone 4; API_SPEC.md).

Every route acts on the signed-in user only (spec §12.3, ownership): there is no user id in the
path, so one user can never address another's data.
"""

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.domains.auth.dependencies import CurrentUser, clear_session_cookie
from app.domains.auth.schemas import AccountDeleteIn, MeOut, MeUpdate
from app.domains.auth.service import AuthService, InvalidCredentialsError, me
from app.domains.users.analytics import TasteAnalytics, TasteAnalyticsOut
from app.domains.users.export import export_user_data
from app.domains.users.schemas import PreferencesIn, PreferencesOut, TasteProfileOut
from app.domains.users.service import (
    InvalidReferenceError,
    TasteProfileService,
    UserError,
    UserService,
)

router = APIRouter(prefix="/users/me", tags=["users"])

Session = Annotated[AsyncSession, Depends(get_db_session)]


def user_http_error(error: UserError) -> HTTPException:
    if isinstance(error, InvalidReferenceError):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": str(error), "kind": error.kind, "values": error.values},
        )
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error))


@router.get("")
async def get_me(user: CurrentUser) -> MeOut:
    return me(user)


@router.patch("")
async def update_me(session: Session, user: CurrentUser, update: MeUpdate) -> MeOut:
    if "display_name" in update.model_fields_set:
        user.display_name = (update.display_name or "").strip() or None
    if update.onboarding_completed is not None:
        user.onboarding_completed_at = (
            (user.onboarding_completed_at or datetime.now(UTC))
            if update.onboarding_completed
            else None
        )
    await session.commit()
    return me(user)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    response: Response, session: Session, user: CurrentUser, data: AccountDeleteIn
) -> None:
    """Delete the account and all of its data (password confirmation required)."""
    try:
        await AuthService(session).delete_account(user, data.password)
    except InvalidCredentialsError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    clear_session_cookie(response)


@router.get("/export")
async def export_me(session: Session, user: CurrentUser) -> Response:
    """Everything TASTIFY stores about the user, as a JSON download (spec §12.4)."""
    data = await export_user_data(session, user)
    return Response(
        json.dumps(data, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="tastify-export.json"'},
    )


@router.get("/preferences")
async def get_preferences(session: Session, user: CurrentUser) -> PreferencesOut:
    return await UserService(session).preferences(user.id)


@router.put("/preferences")
async def put_preferences(
    session: Session, user: CurrentUser, preferences: PreferencesIn
) -> PreferencesOut:
    """Replace the declared preferences; the taste profile is rebuilt immediately."""
    try:
        return await UserService(session).update_preferences(user.id, preferences)
    except UserError as error:
        raise user_http_error(error) from error


@router.get("/taste-profile")
async def taste_profile(
    session: Session,
    user: CurrentUser,
    include_embeddings: Annotated[bool, Query(description="Include the 128-d embeddings")] = False,
) -> TasteProfileOut:
    service = TasteProfileService(session)
    context = await service.current(user.id)
    await session.commit()
    return await service.describe(context, include_embeddings)


@router.get("/taste")
async def taste_analytics(session: Session, user: CurrentUser) -> TasteAnalyticsOut:
    """Taste analytics for the "Your taste" page: only metrics backed by recorded data."""
    return await TasteAnalytics(session).summarize(user.id)
