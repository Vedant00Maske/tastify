"""Interaction endpoints (spec §9: POST /interactions, GET /interactions/history)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.domains.auth.dependencies import CurrentUser
from app.domains.users.events import EventType
from app.domains.users.schemas import (
    FeedbackStates,
    InteractionBatch,
    InteractionHistory,
    InteractionsRecorded,
)
from app.domains.users.service import InvalidReferenceError, UserService

router = APIRouter(prefix="/interactions", tags=["interactions"])

Session = Annotated[AsyncSession, Depends(get_db_session)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def record_interactions(
    session: Session, user: CurrentUser, batch: InteractionBatch
) -> InteractionsRecorded:
    """Record feedback and listening events (play, complete, replay, skip, like, dislike, save,
    playlist_add and their reversals). Idempotent per `client_event_id`; the taste profile is
    updated before the response."""
    try:
        return await UserService(session).record_events(user.id, batch)
    except InvalidReferenceError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": str(error), "kind": error.kind, "values": error.values},
        ) from error


@router.get("/history")
async def interaction_history(
    session: Session,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[datetime | None, Query(description="Only events before this time")] = None,
    event_type: Annotated[
        list[EventType] | None, Query(description="Only these event types (repeatable)")
    ] = None,
) -> InteractionHistory:
    """The user's events, newest first, with track details."""
    return await UserService(session).history(user.id, limit, before, event_type)


@router.get("/state")
async def feedback_state(
    session: Session,
    user: CurrentUser,
    track_id: Annotated[list[uuid.UUID], Query(min_length=1, max_length=200)],
) -> FeedbackStates:
    """Whether each track is currently liked, disliked or saved (for feedback buttons)."""
    return await UserService(session).feedback_states(user.id, track_id)
