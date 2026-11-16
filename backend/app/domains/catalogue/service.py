"""MusicCatalogService (spec §6.6): the catalogue's interface to the rest of the application."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.repository import CatalogueRepository
from app.domains.catalogue.schemas import ArtistDetail, TrackDetail, TrackSummary


class MusicCatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = CatalogueRepository(session)

    async def get_track(self, track_id: uuid.UUID) -> TrackDetail | None:
        return await self.repository.get_track(track_id)

    async def search_tracks(self, query: str, limit: int = 20) -> list[TrackSummary]:
        return await self.repository.search_tracks(query, limit)

    async def get_artist(self, artist_id: uuid.UUID) -> ArtistDetail | None:
        return await self.repository.get_artist(artist_id)

    async def resolve_external_track(self, provider: str, external_id: str) -> TrackDetail | None:
        """The unified track record for any provider's identifier (MBID, ISRC, FMA id, ...)."""
        track_id = await self.repository.find_track_id(provider.lower(), external_id)
        if track_id is None and provider.lower() == "isrc":
            track_id = await self.repository.find_track_id("isrc", external_id.upper())
        return await self.get_track(track_id) if track_id else None
