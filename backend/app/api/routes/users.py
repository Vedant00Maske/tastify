"""User, interaction, preference, taste-profile and personalized recommendation endpoints
(Milestone 3; API_SPEC.md).

There is no authentication until Milestone 4, so these routes take the user id in the path and are
served only when `settings.user_api_enabled` (local and test environments by default). Milestone 4
replaces them with `/users/me/...` behind authentication and ownership checks (spec §12.3).
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db_session
from app.domains.recommendations.personalized import PersonalizedRecommendationService
from app.domains.recommendations.schemas import PersonalizedResponse
from app.domains.recommendations.service import (
    ModelUnavailableError,
    NotFoundError,
    NotInModelError,
    RecommendationError,
)
from app.domains.users.profile import ExplorationMode
from app.domains.users.schemas import (
    InteractionBatch,
    InteractionHistory,
    InteractionsRecorded,
    PreferencesIn,
    PreferencesOut,
    TasteProfileOut,
    UserOut,
)
from app.domains.users.service import (
    InvalidReferenceError,
    TasteProfileService,
    UserError,
    UserNotFoundError,
    UserService,
)


def require_user_api() -> None:
    if not get_settings().user_api_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not Found")


router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_user_api)])

Session = Annotated[AsyncSession, Depends(get_db_session)]
Limit = Annotated[int, Query(ge=1, le=50, description="Number of recommendations")]


def _http_error(error: UserError | RecommendationError) -> HTTPException:
    if isinstance(error, UserNotFoundError | NotFoundError | NotInModelError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, InvalidReferenceError):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": str(error), "kind": error.kind, "values": error.values},
        )
    if isinstance(error, ModelUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    raise error


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(session: Session) -> UserOut:
    """Create a user (development API; Milestone 4 replaces it with registration)."""
    return await UserService(session).create()


@router.get("/{user_id}")
async def get_user(session: Session, user_id: uuid.UUID) -> UserOut:
    try:
        return await UserService(session).get(user_id)
    except UserError as error:
        raise _http_error(error) from error


@router.post("/{user_id}/interactions", status_code=status.HTTP_201_CREATED)
async def record_interactions(
    session: Session, user_id: uuid.UUID, batch: InteractionBatch
) -> InteractionsRecorded:
    """Record interaction events (plays, skips, likes, saves, ...) and update the taste profile.

    Idempotent per `client_event_id`: retrying a batch does not record its events twice."""
    try:
        return await UserService(session).record_events(user_id, batch)
    except UserError as error:
        raise _http_error(error) from error


@router.get("/{user_id}/interactions")
async def interaction_history(
    session: Session,
    user_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[datetime | None, Query(description="Only events before this time")] = None,
) -> InteractionHistory:
    try:
        return await UserService(session).history(user_id, limit, before)
    except UserError as error:
        raise _http_error(error) from error


@router.get("/{user_id}/preferences")
async def get_preferences(session: Session, user_id: uuid.UUID) -> PreferencesOut:
    try:
        return await UserService(session).preferences(user_id)
    except UserError as error:
        raise _http_error(error) from error


@router.put("/{user_id}/preferences")
async def put_preferences(
    session: Session, user_id: uuid.UUID, preferences: PreferencesIn
) -> PreferencesOut:
    """Replace the user's declared preferences: exploration mode, favourite and excluded artists
    and genres, and the personalization opt-out. The taste profile is rebuilt immediately."""
    try:
        return await UserService(session).update_preferences(user_id, preferences)
    except UserError as error:
        raise _http_error(error) from error


@router.get("/{user_id}/taste-profile")
async def taste_profile(
    session: Session,
    user_id: uuid.UUID,
    include_embeddings: Annotated[bool, Query(description="Include the 128-d embeddings")] = False,
) -> TasteProfileOut:
    try:
        service = TasteProfileService(session)
        context = await service.current(user_id)
        await session.commit()
        return await service.describe(context, include_embeddings)
    except UserError as error:
        raise _http_error(error) from error


@router.get("/{user_id}/recommendations")
async def for_you(
    session: Session,
    user_id: uuid.UUID,
    limit: Limit = 25,
    exploration: Annotated[
        ExplorationMode | None,
        Query(description="Override the user's exploration mode for this request"),
    ] = None,
) -> PersonalizedResponse:
    """The personalized mix ("for you"): hybrid ranking over every candidate source, diversified,
    balancing familiar artists and discoveries (familiar 80/20, balanced 50/50, explorer 20/80)."""
    try:
        response = await PersonalizedRecommendationService(session).for_you(
            user_id, limit, exploration
        )
        await session.commit()
        return response
    except (UserError, RecommendationError) as error:
        raise _http_error(error) from error
