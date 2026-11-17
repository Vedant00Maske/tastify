"""Playlist endpoints (Milestone 4; API_SPEC.md). All act on the signed-in user's playlists."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.domains.auth.dependencies import CurrentUser
from app.domains.playlists.schemas import (
    PlaylistCreate,
    PlaylistDetail,
    PlaylistList,
    PlaylistUpdate,
    TracksAdd,
    TracksOrder,
)
from app.domains.playlists.service import (
    PlaylistError,
    PlaylistNotFoundError,
    PlaylistService,
)
from app.domains.recommendations.schemas import RecommendationResponse
from app.domains.recommendations.service import (
    ModelUnavailableError,
    NotFoundError,
    NotInModelError,
    RecommendationError,
)

router = APIRouter(prefix="/playlists", tags=["playlists"])

Session = Annotated[AsyncSession, Depends(get_db_session)]


def _http_error(error: PlaylistError | RecommendationError) -> HTTPException:
    if isinstance(error, PlaylistNotFoundError | NotFoundError | NotInModelError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, ModelUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


Errors = (PlaylistError, RecommendationError)


@router.get("")
async def list_playlists(session: Session, user: CurrentUser) -> PlaylistList:
    return await PlaylistService(session).list(user.id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_playlist(
    session: Session, user: CurrentUser, data: PlaylistCreate
) -> PlaylistDetail:
    """Create a playlist from tracks, or from a generator (for you, mood, hidden gems, genre,
    artist radio) that also lets it be regenerated later."""
    try:
        return await PlaylistService(session).create(user.id, data)
    except Errors as error:
        raise _http_error(error) from error


@router.get("/{playlist_id}")
async def get_playlist(
    session: Session, user: CurrentUser, playlist_id: uuid.UUID
) -> PlaylistDetail:
    try:
        return await PlaylistService(session).get(user.id, playlist_id)
    except Errors as error:
        raise _http_error(error) from error


@router.patch("/{playlist_id}")
async def update_playlist(
    session: Session, user: CurrentUser, playlist_id: uuid.UUID, data: PlaylistUpdate
) -> PlaylistDetail:
    try:
        return await PlaylistService(session).update(user.id, playlist_id, data)
    except Errors as error:
        raise _http_error(error) from error


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist(session: Session, user: CurrentUser, playlist_id: uuid.UUID) -> None:
    try:
        await PlaylistService(session).delete(user.id, playlist_id)
    except Errors as error:
        raise _http_error(error) from error


@router.post("/{playlist_id}/tracks")
async def add_tracks(
    session: Session, user: CurrentUser, playlist_id: uuid.UUID, data: TracksAdd
) -> PlaylistDetail:
    """Append tracks (duplicates are skipped). Records `playlist_add` feedback."""
    try:
        return await PlaylistService(session).add_tracks(user.id, playlist_id, data.track_ids)
    except Errors as error:
        raise _http_error(error) from error


@router.delete("/{playlist_id}/tracks/{track_id}")
async def remove_track(
    session: Session, user: CurrentUser, playlist_id: uuid.UUID, track_id: uuid.UUID
) -> PlaylistDetail:
    try:
        return await PlaylistService(session).remove_track(user.id, playlist_id, track_id)
    except Errors as error:
        raise _http_error(error) from error


@router.put("/{playlist_id}/tracks/order")
async def reorder_tracks(
    session: Session, user: CurrentUser, playlist_id: uuid.UUID, data: TracksOrder
) -> PlaylistDetail:
    try:
        return await PlaylistService(session).reorder(user.id, playlist_id, data.track_ids)
    except Errors as error:
        raise _http_error(error) from error


@router.post("/{playlist_id}/regenerate")
async def regenerate_playlist(
    session: Session, user: CurrentUser, playlist_id: uuid.UUID
) -> PlaylistDetail:
    """Replace a generated playlist's tracks with a fresh set from its generator."""
    try:
        return await PlaylistService(session).regenerate(user.id, playlist_id)
    except Errors as error:
        raise _http_error(error) from error


@router.get("/{playlist_id}/suggestions")
async def playlist_suggestions(
    session: Session,
    user: CurrentUser,
    playlist_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> RecommendationResponse:
    """Tracks that fit the playlist's sound, to add."""
    try:
        return await PlaylistService(session).suggestions(user.id, playlist_id, limit)
    except Errors as error:
        raise _http_error(error) from error
