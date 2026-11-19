"""MusicBrainz: public recording search (no account; ADR-018).

Used where the TASTIFY catalogue has no match, to point the user at the recording on
MusicBrainz. At most one request per second with a descriptive User-Agent (MusicBrainz rules).
"""

from typing import Any

import httpx

from app.core.config import get_settings
from app.domains.integrations.clients.base import ProviderError, RateLimitedClient
from app.domains.integrations.clients.metabrainz import MUSICBRAINZ_API
from app.domains.integrations.providers.base import (
    AuthKind,
    Capability,
    ExternalRecording,
    MusicProvider,
    translate,
)


def _lucene(text: str) -> str:
    """Escape Lucene query syntax so user input is searched as plain words."""
    special = set(r'+-&|!(){}[]^"~*?:\/')
    return "".join(rf"\{ch}" if ch in special else ch for ch in text)


def build_query(text: str) -> str:
    """Exact title phrase first, else the words in both title and artist ("radiohead karma
    police"). Checked against live MusicBrainz results: a plain word query ranks covers whose
    titles mention the artist above the recording itself."""
    words = _lucene(" ".join(text.split()))
    return f'recording:"{words}"^4 OR (recording:({words}) AND artist:({words}))^2'


def _recording(item: dict[str, Any]) -> ExternalRecording:
    credits = item.get("artist-credit") or []
    artist = "".join(
        f"{c.get('name') or (c.get('artist') or {}).get('name', '')}{c.get('joinphrase', '')}"
        for c in credits
    )
    releases = item.get("releases") or []
    mbid = str(item["id"])
    return ExternalRecording(
        mbid=mbid,
        title=str(item.get("title") or ""),
        artist=artist,
        release=str(releases[0].get("title")) if releases else None,
        length_ms=int(item["length"]) if isinstance(item.get("length"), int) else None,
        url=f"https://musicbrainz.org/recording/{mbid}",
    )


class MusicBrainzProvider(MusicProvider):
    name = "musicbrainz"
    display_name = "MusicBrainz"
    auth = AuthKind.NONE
    capabilities = frozenset({Capability.SEARCH_TRACKS})

    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, *, min_interval: float = 1.0
    ) -> None:
        super().__init__(transport)
        self.min_interval = min_interval

    async def search_recordings(self, query: str, limit: int) -> list[ExternalRecording]:
        try:
            async with RateLimitedClient(
                MUSICBRAINZ_API,
                get_settings().metabrainz_user_agent,
                min_interval=self.min_interval,
                max_retries=2,
                timeout=10.0,
                transport=self.transport,
                max_wait=5.0,
            ) as client:
                result = await client.request_json(
                    "GET",
                    "recording",
                    params={"query": build_query(query), "limit": limit, "fmt": "json"},
                )
        except ProviderError as error:
            raise translate(self.display_name, error) from error
        return [_recording(item) for item in (result or {}).get("recordings", []) if item.get("id")]
