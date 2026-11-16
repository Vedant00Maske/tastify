"""Music catalogue endpoints (spec §9: /tracks, /artists)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.domains.catalogue.schemas import ArtistDetail, TrackDetail, TrackSearchResponse
from app.domains.catalogue.service import MusicCatalogService

router = APIRouter(tags=["catalogue"])


def get_catalogue_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MusicCatalogService:
    return MusicCatalogService(session)


Catalogue = Annotated[MusicCatalogService, Depends(get_catalogue_service)]


def _not_found(entity: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{entity} not found")


@router.get("/tracks/search")
async def search_tracks(
    catalogue: Catalogue,
    q: Annotated[str, Query(min_length=2, max_length=200, description="Artist and/or title")],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> TrackSearchResponse:
    return TrackSearchResponse(query=q, results=await catalogue.search_tracks(q, limit))


@router.get("/tracks/lookup")
async def lookup_track(
    catalogue: Catalogue,
    provider: Annotated[str, Query(min_length=1, max_length=32, examples=["musicbrainz", "isrc"])],
    external_id: Annotated[str, Query(min_length=1, max_length=200)],
) -> TrackDetail:
    """The unified track record for an identifier from any provider."""
    track = await catalogue.resolve_external_track(provider, external_id)
    if track is None:
        raise _not_found("Track")
    return track


@router.get("/tracks/{track_id}")
async def get_track(catalogue: Catalogue, track_id: uuid.UUID) -> TrackDetail:
    track = await catalogue.get_track(track_id)
    if track is None:
        raise _not_found("Track")
    return track


@router.get("/artists/{artist_id}")
async def get_artist(catalogue: Catalogue, artist_id: uuid.UUID) -> ArtistDetail:
    artist = await catalogue.get_artist(artist_id)
    if artist is None:
        raise _not_found("Artist")
    return artist
