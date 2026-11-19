"""YouTube: playlist export with Google OAuth (ADR-018).

The Data API's default quota is 10,000 units a day; `search.list` costs 100 units, inserts and
deletes 50, list calls 1 (Google's quota table, INTEGRATIONS.md). Every call reserves its units
first (`spend`), exports are capped at `max_export_tracks`, and found video ids are cached and
re-checked after 30 days (YouTube developer policies on storing API data).

Exports are private playlists. Re-exporting compares the remote items with the wanted list and
only inserts the missing videos and deletes the extra ones, so a retry never duplicates items.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from app.core.config import get_settings
from app.domains.integrations.clients.base import ProviderError, RateLimitedClient
from app.domains.integrations.providers.base import (
    Account,
    AuthKind,
    Capability,
    ExportTrack,
    InvalidCredentialsError,
    MusicProvider,
    ProviderNotConfiguredError,
    ProviderRejectedError,
    QuotaExceededError,
    RemotePlaylist,
    Spend,
    translate,
)

AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint URL, not a secret
REVOKE = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3/"
SCOPE = "https://www.googleapis.com/auth/youtube"

COST_LIST = 1
COST_SEARCH = 100
COST_WRITE = 50
MUSIC_CATEGORY = "10"


class YouTubeProvider(MusicProvider):
    name = "youtube"
    display_name = "YouTube"
    auth = AuthKind.OAUTH
    capabilities = frozenset({Capability.EXPORT_PLAYLIST})
    max_export_tracks = 50  # about 7,600 units in the worst case: within one day's quota

    def available(self) -> bool:
        settings = get_settings()
        return bool(settings.google_client_id and settings.google_client_secret)

    def _credentials(self) -> tuple[str, str]:
        settings = get_settings()
        if not settings.google_client_id or not settings.google_client_secret:
            raise ProviderNotConfiguredError("YouTube is not configured on this server")
        return settings.google_client_id, settings.google_client_secret

    def _client(self, base: str = API) -> RateLimitedClient:
        return RateLimitedClient(
            base,
            get_settings().metabrainz_user_agent,
            min_interval=0.1,
            max_retries=3,
            timeout=20.0,
            transport=self.transport,
            max_wait=10.0,
            # Google signals quota exhaustion with 403 (not retried) and overload with 5xx.
        )

    def _translate(self, error: ProviderError) -> Exception:
        text = str(error)
        if error.status_code == 403 and ("quotaExceeded" in text or "dailyLimitExceeded" in text):
            return QuotaExceededError("YouTube")
        if error.status_code == 403:
            return ProviderRejectedError("YouTube refused the request")
        return translate(self.display_name, error)

    async def _api(self, token: str, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with self._client() as client:
                return await client.request_json(
                    method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
                )
        except ProviderError as error:
            raise self._translate(error) from error

    # --- OAuth --------------------------------------------------------------------------------

    def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        client_id, _secret = self._credentials()
        query = {
            "response_type": "code",
            "client_id": client_id,
            "scope": SCOPE,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
            "access_type": "offline",  # a refresh token, so exports work after an hour
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        return f"{AUTHORIZE}?{urlencode(query)}"

    async def _token(self, form: dict[str, str]) -> dict[str, Any]:
        client_id, secret = self._credentials()
        try:
            async with self._client(TOKEN_URL) as client:
                result = await client.request_json(
                    "POST", "", data={**form, "client_id": client_id, "client_secret": secret}
                )
        except ProviderError as error:
            if error.status_code in (400, 401):
                raise InvalidCredentialsError("Google did not accept the authorization") from error
            raise self._translate(error) from error
        return dict(result or {})

    @staticmethod
    def _expiry(result: dict[str, Any]) -> datetime | None:
        seconds = result.get("expires_in")
        return datetime.now(UTC) + timedelta(seconds=int(seconds)) if seconds else None

    async def exchange_code(self, code: str, code_verifier: str, redirect_uri: str) -> Account:
        result = await self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        access = str(result.get("access_token") or "")
        if not access:
            raise InvalidCredentialsError("Google returned no access token")
        channels = await self._api(
            access, "GET", "channels", params={"part": "snippet", "mine": "true"}
        )
        items = (channels or {}).get("items") or []
        if not items:
            raise ProviderRejectedError(
                "This Google account has no YouTube channel to hold playlists"
            )
        channel = items[0]
        return Account(
            external_user_id=str(channel["id"]),
            external_name=(channel.get("snippet") or {}).get("title"),
            access_token=access,
            refresh_token=result.get("refresh_token"),
            expires_at=self._expiry(result),
            scopes=tuple(str(result.get("scope") or SCOPE).split()),
        )

    async def refresh(self, refresh_token: str) -> Account:
        result = await self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})
        return Account(
            external_user_id="",
            external_name=None,
            access_token=str(result["access_token"]),
            refresh_token=result.get("refresh_token") or refresh_token,
            expires_at=self._expiry(result),
            scopes=tuple(str(result.get("scope") or SCOPE).split()),
        )

    async def revoke(self, token: str) -> None:
        try:
            async with self._client(REVOKE) as client:
                await client.request("POST", "", data={"token": token})
        except ProviderError:
            return None  # best effort: the stored tokens are deleted either way

    # --- export -------------------------------------------------------------------------------

    def export_cost(self, tracks: int, unresolved: int, existing_playlist: bool) -> int:
        """Units an export may need: an upper bound checked before starting (each call still
        reserves its own units, so the daily budget is never overshot either way)."""
        pages = max(1, -(-tracks // 50))
        if existing_playlist:
            # Worst case on re-export: every item replaced (deleted and inserted again).
            playlist = COST_LIST + pages * COST_LIST + 2 * COST_WRITE * tracks
        else:
            # Look for it by its marker, create it, insert every video (nothing to delete).
            playlist = COST_LIST + COST_WRITE + pages * COST_LIST + COST_WRITE * tracks
        return COST_SEARCH * unresolved + playlist

    async def resolve_track(self, token: str, track: ExportTrack, spend: Spend) -> str | None:
        await spend(COST_SEARCH)
        result = await self._api(
            token,
            "GET",
            "search",
            params={
                "part": "id",
                "type": "video",
                "videoCategoryId": MUSIC_CATEGORY,
                "maxResults": 1,
                "q": f"{track.artist} {track.title}",
            },
        )
        items = (result or {}).get("items") or []
        video = (items[0].get("id") or {}).get("videoId") if items else None
        return str(video) if video else None

    @staticmethod
    def _url(playlist_id: str) -> str:
        return f"https://www.youtube.com/playlist?list={playlist_id}"

    async def get_playlist(
        self, token: str, playlist_id: str, spend: Spend
    ) -> RemotePlaylist | None:
        await spend(COST_LIST)
        result = await self._api(
            token, "GET", "playlists", params={"part": "id", "id": playlist_id}
        )
        if not (result or {}).get("items"):
            return None
        return RemotePlaylist(playlist_id, self._url(playlist_id))

    async def find_playlist(
        self, token: str, account_id: str, marker: str, spend: Spend
    ) -> RemotePlaylist | None:
        await spend(COST_LIST)
        result = await self._api(
            token, "GET", "playlists", params={"part": "snippet", "mine": "true", "maxResults": 50}
        )
        for playlist in (result or {}).get("items") or []:
            if marker in str((playlist.get("snippet") or {}).get("description") or ""):
                return RemotePlaylist(str(playlist["id"]), self._url(str(playlist["id"])))
        return None

    async def create_playlist(
        self, token: str, name: str, description: str, spend: Spend
    ) -> RemotePlaylist:
        await spend(COST_WRITE)
        playlist = await self._api(
            token,
            "POST",
            "playlists",
            params={"part": "snippet,status"},
            json={
                "snippet": {"title": name[:150], "description": description[:5000]},
                "status": {"privacyStatus": "private"},
            },
        )
        return RemotePlaylist(str(playlist["id"]), self._url(str(playlist["id"])))

    async def _items(self, token: str, playlist_id: str, spend: Spend) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        page_token: str | None = None
        while True:
            await spend(COST_LIST)
            params: dict[str, Any] = {
                "part": "snippet",
                "playlistId": playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            result = await self._api(token, "GET", "playlistItems", params=params)
            for item in (result or {}).get("items") or []:
                video = ((item.get("snippet") or {}).get("resourceId") or {}).get("videoId")
                if video:
                    found.append((str(item["id"]), str(video)))
            page_token = (result or {}).get("nextPageToken")
            if not page_token:
                return found

    async def replace_items(
        self, token: str, playlist_id: str, item_ids: Sequence[str], spend: Spend
    ) -> None:
        wanted = list(dict.fromkeys(item_ids))
        existing = await self._items(token, playlist_id, spend)
        if [video for _, video in existing] == wanted:
            return
        keep: set[str] = set()
        for item_id, video in existing:
            if video in wanted and video not in keep:
                keep.add(video)
                continue
            await spend(COST_WRITE)
            await self._api(token, "DELETE", "playlistItems", params={"id": item_id})
        for position, video in enumerate(wanted):
            if video in keep:
                continue
            await spend(COST_WRITE)
            await self._api(
                token,
                "POST",
                "playlistItems",
                params={"part": "snippet"},
                json={
                    "snippet": {
                        "playlistId": playlist_id,
                        "position": position,
                        "resourceId": {"kind": "youtube#video", "videoId": video},
                    }
                },
            )
