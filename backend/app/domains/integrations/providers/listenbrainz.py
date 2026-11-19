"""ListenBrainz: listening-history import and playlist export (INTEGRATIONS.md, ADR-018).

- Auth: the user's personal token (`Authorization: Token …`), checked with /1/validate-token.
- Import: the newest listens, 1,000 per request, at most `MAX_PAGES` requests per run, then
  incrementally newer than the last imported one. ListenBrainz asks clients not to page through a
  whole history with this endpoint (its export API is for full archives).
- Export: a private playlist of recording MBIDs (JSPF), replaced item by item on re-export.
- At most one request per second; `X-RateLimit-*` headers are honoured by the client.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import get_settings
from app.domains.integrations.clients.base import ProviderError, RateLimitedClient
from app.domains.integrations.providers.base import (
    Account,
    AuthKind,
    Capability,
    ExportTrack,
    ExternalItem,
    ImportBatch,
    InvalidCredentialsError,
    MusicProvider,
    RemotePlaylist,
    Spend,
    translate,
)

API = "https://api.listenbrainz.org/1/"
PAGE_SIZE = 1000  # MAX_ITEMS_PER_GET
MAX_PAGES = 10  # ListenBrainz: "roughly ten pages or fewer" with the listens endpoint
ADD_BATCH = 100  # MAX_RECORDINGS_PER_ADD
RECORDING_URI = "https://musicbrainz.org/recording/"
JSPF_PLAYLIST = "https://musicbrainz.org/doc/jspf#playlist"


def _mbid(listen: dict[str, Any]) -> str | None:
    metadata = listen.get("track_metadata") or {}
    mapped = (metadata.get("mbid_mapping") or {}).get("recording_mbid")
    submitted = (metadata.get("additional_info") or {}).get("recording_mbid")
    value = mapped or submitted
    return str(value) if value else None


def listen_to_item(listen: dict[str, Any]) -> ExternalItem | None:
    metadata = listen.get("track_metadata") or {}
    artist, title = metadata.get("artist_name"), metadata.get("track_name")
    listened_at = listen.get("listened_at")
    if not artist or not title or not isinstance(listened_at, int):
        return None
    mbid = _mbid(listen)
    isrc = (metadata.get("additional_info") or {}).get("isrc")
    identity = listen.get("recording_msid") or mbid or f"{artist}|{title}"
    return ExternalItem(
        key=f"{listened_at}:{identity}",
        event_type="play",
        occurred_at=datetime.fromtimestamp(listened_at, UTC),
        artist=str(artist),
        title=str(title),
        recording_mbid=mbid,
        isrc=str(isrc) if isrc else None,
    )


class ListenBrainzProvider(MusicProvider):
    name = "listenbrainz"
    display_name = "ListenBrainz"
    auth = AuthKind.TOKEN
    capabilities = frozenset({Capability.IMPORT_HISTORY, Capability.EXPORT_PLAYLIST})

    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, *, min_interval: float = 1.0
    ) -> None:
        super().__init__(transport)
        self.min_interval = min_interval

    def _client(self) -> RateLimitedClient:
        return RateLimitedClient(
            API,
            get_settings().metabrainz_user_agent,
            min_interval=self.min_interval,
            max_retries=3,
            timeout=20.0,
            transport=self.transport,
            max_wait=10.0,
        )

    async def _call(self, token: str, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Token {token}"}
        try:
            async with self._client() as client:
                return await client.request_json(method, path, headers=headers, **kwargs)
        except ProviderError as error:
            raise translate(self.display_name, error) from error

    async def connect_with_token(self, token: str) -> Account:
        result = await self._call(token, "GET", "validate-token")
        if not result or not result.get("valid") or not result.get("user_name"):
            raise InvalidCredentialsError("ListenBrainz did not accept this token")
        name = str(result["user_name"])
        return Account(external_user_id=name, external_name=name, access_token=token)

    async def fetch_history(self, token: str, account_id: str, cursor: str | None) -> ImportBatch:
        since = int(cursor) if cursor and cursor.isdigit() else None
        items: list[ExternalItem] = []
        newest = since
        max_ts: int | None = None
        complete = False
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {"count": PAGE_SIZE}
            if max_ts is not None:
                params["max_ts"] = max_ts
            payload = await self._call(token, "GET", f"user/{account_id}/listens", params=params)
            listens = list((payload or {}).get("payload", {}).get("listens", []))
            if not listens:
                complete = True
                break
            reached_known = False
            for listen in listens:
                listened_at = listen.get("listened_at")
                if not isinstance(listened_at, int):
                    continue
                if since is not None and listened_at <= since:
                    reached_known = True
                    break
                newest = max(newest or 0, listened_at)
                item = listen_to_item(listen)
                if item is not None:
                    items.append(item)
            if reached_known or len(listens) < PAGE_SIZE:
                complete = True
                break
            max_ts = min(
                int(x["listened_at"]) for x in listens if isinstance(x.get("listened_at"), int)
            )
        return ImportBatch(
            items=items, cursor=str(newest) if newest is not None else cursor, complete=complete
        )

    # --- export -------------------------------------------------------------------------------

    @staticmethod
    def _url(mbid: str) -> str:
        return f"https://listenbrainz.org/playlist/{mbid}/"

    async def resolve_track(self, token: str, track: ExportTrack, spend: Spend) -> str | None:
        return track.recording_mbid  # ListenBrainz playlists are made of recording MBIDs

    async def get_playlist(
        self, token: str, playlist_id: str, spend: Spend
    ) -> RemotePlaylist | None:
        try:
            async with self._client() as client:
                await client.request_json(
                    "GET",
                    f"playlist/{playlist_id}",
                    params={"fetch_metadata": "false"},
                    headers={"Authorization": f"Token {token}"},
                )
        except ProviderError as error:
            if error.status_code == 404:
                return None
            raise translate(self.display_name, error) from error
        return RemotePlaylist(playlist_id, self._url(playlist_id))

    async def find_playlist(
        self, token: str, account_id: str, marker: str, spend: Spend
    ) -> RemotePlaylist | None:
        payload = await self._call(
            token, "GET", f"user/{account_id}/playlists", params={"count": 100}
        )
        for entry in (payload or {}).get("playlists", []):
            playlist = entry.get("playlist") or {}
            if marker in str(playlist.get("annotation") or ""):
                identifier = str(playlist.get("identifier") or "").rstrip("/")
                mbid = identifier.rsplit("/", 1)[-1]
                if mbid:
                    return RemotePlaylist(mbid, self._url(mbid))
        return None

    async def create_playlist(
        self, token: str, name: str, description: str, spend: Spend
    ) -> RemotePlaylist:
        body = {
            "playlist": {
                "title": name,
                "annotation": description,
                "track": [],
                "extension": {JSPF_PLAYLIST: {"public": False}},
            }
        }
        result = await self._call(token, "POST", "playlist/create", json=body)
        mbid = str((result or {}).get("playlist_mbid") or "")
        if not mbid:
            raise translate(self.display_name, ProviderError("no playlist id", status_code=502))
        return RemotePlaylist(mbid, self._url(mbid))

    async def replace_items(
        self, token: str, playlist_id: str, item_ids: Sequence[str], spend: Spend
    ) -> None:
        current = await self._call(
            token, "GET", f"playlist/{playlist_id}", params={"fetch_metadata": "false"}
        )
        existing = len(((current or {}).get("playlist") or {}).get("track") or [])
        if existing:
            await self._call(
                token,
                "POST",
                f"playlist/{playlist_id}/item/delete",
                json={"index": 0, "count": existing},
            )
        for start in range(0, len(item_ids), ADD_BATCH):
            tracks = [
                {"identifier": [f"{RECORDING_URI}{mbid}"]}
                for mbid in item_ids[start : start + ADD_BATCH]
            ]
            await self._call(
                token,
                "POST",
                f"playlist/{playlist_id}/item/add",
                json={"playlist": {"track": tracks}},
            )
