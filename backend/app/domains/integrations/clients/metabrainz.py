"""Read-only clients for the MusicBrainz web service and the ListenBrainz API."""

from collections.abc import Sequence
from typing import Any

import httpx

from app.domains.integrations.clients.base import RateLimitedClient, Sleep

MUSICBRAINZ_API = "https://musicbrainz.org/ws/2/"
LISTENBRAINZ_API = "https://api.listenbrainz.org/1/"


class MusicBrainzClient(RateLimitedClient):
    PAGE_SIZE = 100  # maximum allowed by the web service

    def __init__(
        self,
        user_agent: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        extra: dict[str, Any] = {"sleep": sleep} if sleep else {}
        super().__init__(
            MUSICBRAINZ_API, user_agent, min_interval=1.0, transport=transport, **extra
        )

    async def all_genres(self) -> list[dict[str, str]]:
        """Every genre MusicBrainz recognises: [{"id": mbid, "name": ...}]."""
        genres: list[dict[str, str]] = []
        offset = 0
        while True:
            page = await self.request_json(
                "GET",
                "genre/all",
                params={"fmt": "json", "limit": self.PAGE_SIZE, "offset": offset},
            )
            batch = page.get("genres", [])
            genres.extend({"id": g["id"], "name": g["name"]} for g in batch)
            offset += len(batch)
            if not batch or offset >= page.get("genre-count", 0):
                return genres


class ListenBrainzClient(RateLimitedClient):
    def __init__(
        self,
        user_agent: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep | None = None,
    ) -> None:
        extra: dict[str, Any] = {"sleep": sleep} if sleep else {}
        super().__init__(
            LISTENBRAINZ_API, user_agent, min_interval=1.0, transport=transport, **extra
        )

    async def recording_metadata(
        self, recording_mbids: Sequence[str], inc: str = "artist tag release"
    ) -> dict[str, dict[str, Any]]:
        """MusicBrainz metadata (credits, ISRCs, release group, tags) for many recordings."""
        result = await self.request_json(
            "POST",
            "metadata/recording/",
            json={"recording_mbids": list(recording_mbids), "inc": inc},
        )
        return dict(result or {})

    async def sitewide_top_recordings(
        self, count: int = 1000, time_range: str = "all_time"
    ) -> list[dict[str, Any]]:
        payload = await self.request_json(
            "GET", "stats/sitewide/recordings", params={"count": count, "range": time_range}
        )
        return list((payload or {}).get("payload", {}).get("recordings", []))
