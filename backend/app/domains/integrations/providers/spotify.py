"""Spotify: library import and playlist export, where Development Mode permits (ADR-018).

Confirmed against Spotify's February 2026 migration guide (INTEGRATIONS.md):
- OAuth authorization code with PKCE; the client secret is not needed.
- Import: saved tracks (`GET /me/tracks`, as likes) and recently played (`GET /me/player/
  recently-played`, as plays).
- Export: `POST /me/playlists`, then `PUT /playlists/{id}/items` (replaces, idempotent, at most
  100 items) and `POST /playlists/{id}/items` for the rest.
- Matching: search `isrc:` (track objects still carry `external_ids.isrc`); otherwise a title and
  artist search whose top results must match exactly. Search returns at most 10 results.
- Development Mode: the app owner needs Premium and at most 5 allow-listed users may connect;
  others get 403. TASTIFY never calls Spotify's recommendation or audio-feature endpoints.
"""

import base64
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from app.core.config import get_settings
from app.domains.catalogue.writer import track_matching_key
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
    ProviderNotConfiguredError,
    ProviderRejectedError,
    QuotaExceededError,
    RemotePlaylist,
    Spend,
    translate,
)

AUTHORIZE = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"  # noqa: S105 - endpoint URL, not a secret
API = "https://api.spotify.com/v1/"
SCOPES = (
    "user-library-read",
    "user-read-recently-played",
    "playlist-read-private",
    "playlist-modify-private",
    "playlist-modify-public",
)
PAGE = 50
MAX_SAVED_PAGES = 20  # the newest 1,000 saved tracks per import
ITEMS_PER_CALL = 100


def _item(track: dict[str, Any], key: str, event: str, when: str) -> ExternalItem | None:
    artists = track.get("artists") or []
    if not track.get("name") or not artists:
        return None
    try:
        occurred = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError:
        return None
    isrc = (track.get("external_ids") or {}).get("isrc")
    return ExternalItem(
        key=key,
        event_type=event,
        occurred_at=occurred,
        artist=str(artists[0].get("name") or ""),
        title=str(track["name"]),
        isrc=str(isrc).upper() if isrc else None,
    )


class SpotifyProvider(MusicProvider):
    name = "spotify"
    display_name = "Spotify"
    auth = AuthKind.OAUTH
    capabilities = frozenset({Capability.IMPORT_HISTORY, Capability.EXPORT_PLAYLIST})

    def available(self) -> bool:
        return bool(get_settings().spotify_client_id)

    def _client_id(self) -> str:
        client_id = get_settings().spotify_client_id
        if not client_id:
            raise ProviderNotConfiguredError("Spotify is not configured on this server")
        return client_id

    def _client(self, base: str = API) -> RateLimitedClient:
        return RateLimitedClient(
            base,
            get_settings().metabrainz_user_agent,
            min_interval=0.1,
            max_retries=3,
            timeout=20.0,
            transport=self.transport,
            max_wait=10.0,
        )

    def _translate(self, error: ProviderError) -> Exception:
        if error.status_code == 403:
            return ProviderRejectedError(
                "Spotify refused the request. Apps in Development Mode only serve up to five "
                "Spotify accounts that the app owner has allow-listed."
            )
        if error.status_code == 429 and "QUOTA_EXCEEDED" in str(error):
            return QuotaExceededError("Spotify")
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
        query = {
            "response_type": "code",
            "client_id": self._client_id(),
            "scope": " ".join(SCOPES),
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
        }
        return f"{AUTHORIZE}?{urlencode(query)}"

    async def _token(self, form: dict[str, str]) -> dict[str, Any]:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        secret = get_settings().spotify_client_secret
        if secret:
            pair = f"{self._client_id()}:{secret}".encode()
            headers["Authorization"] = f"Basic {base64.b64encode(pair).decode()}"
        try:
            async with self._client(TOKEN_URL) as client:
                result = await client.request_json("POST", "", data=form, headers=headers)
        except ProviderError as error:
            if error.status_code in (400, 401):
                raise InvalidCredentialsError("Spotify did not accept the authorization") from error
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
                "client_id": self._client_id(),
                "code_verifier": code_verifier,
            }
        )
        access = str(result.get("access_token") or "")
        if not access:
            raise InvalidCredentialsError("Spotify returned no access token")
        me = await self._api(access, "GET", "me")
        return Account(
            external_user_id=str(me["id"]),
            external_name=me.get("display_name") or str(me["id"]),
            access_token=access,
            refresh_token=result.get("refresh_token"),
            expires_at=self._expiry(result),
            scopes=tuple(str(result.get("scope") or "").split()),
        )

    async def refresh(self, refresh_token: str) -> Account:
        result = await self._token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id(),
            }
        )
        return Account(
            external_user_id="",
            external_name=None,
            access_token=str(result["access_token"]),
            # Spotify may rotate the refresh token; keep the old one when it does not.
            refresh_token=result.get("refresh_token") or refresh_token,
            expires_at=self._expiry(result),
            scopes=tuple(str(result.get("scope") or "").split()),
        )

    # --- import -------------------------------------------------------------------------------

    async def fetch_history(self, token: str, account_id: str, cursor: str | None) -> ImportBatch:
        items: list[ExternalItem] = []
        complete = True
        for page in range(MAX_SAVED_PAGES):
            saved = await self._api(
                token, "GET", "me/tracks", params={"limit": PAGE, "offset": page * PAGE}
            )
            entries = list((saved or {}).get("items") or [])
            for entry in entries:
                track = entry.get("track") or {}
                item = _item(track, f"saved:{track.get('id')}", "like", str(entry.get("added_at")))
                if item is not None:
                    items.append(item)
            if not (saved or {}).get("next") or not entries:
                break
            if page == MAX_SAVED_PAGES - 1:
                complete = False

        params: dict[str, Any] = {"limit": PAGE}
        if cursor and cursor.isdigit():
            params["after"] = int(cursor)
        recent = await self._api(token, "GET", "me/player/recently-played", params=params)
        newest = int(cursor) if cursor and cursor.isdigit() else 0
        for entry in (recent or {}).get("items") or []:
            played_at = str(entry.get("played_at") or "")
            track = entry.get("track") or {}
            item = _item(track, f"played:{played_at}:{track.get('id')}", "play", played_at)
            if item is not None:
                items.append(item)
                newest = max(newest, int(item.occurred_at.timestamp() * 1000))
        return ImportBatch(items=items, cursor=str(newest) if newest else cursor, complete=complete)

    # --- export -------------------------------------------------------------------------------

    async def resolve_track(self, token: str, track: ExportTrack, spend: Spend) -> str | None:
        if track.isrc:
            found = await self._api(
                token,
                "GET",
                "search",
                params={"q": f"isrc:{track.isrc}", "type": "track", "limit": 1},
            )
            hits = ((found or {}).get("tracks") or {}).get("items") or []
            if hits:
                return str(hits[0]["uri"])
        query = f'track:"{track.title}" artist:"{track.artist}"'
        found = await self._api(
            token, "GET", "search", params={"q": query, "type": "track", "limit": 5}
        )
        wanted = track_matching_key(track.artist, track.title)
        for hit in ((found or {}).get("tracks") or {}).get("items") or []:
            artists = hit.get("artists") or []
            if (
                artists
                and track_matching_key(str(artists[0].get("name")), str(hit.get("name"))) == wanted
            ):
                return str(hit["uri"])
        return None

    @staticmethod
    def _remote(playlist: dict[str, Any]) -> RemotePlaylist:
        url = (playlist.get("external_urls") or {}).get("spotify")
        return RemotePlaylist(str(playlist["id"]), str(url) if url else None)

    async def get_playlist(
        self, token: str, playlist_id: str, spend: Spend
    ) -> RemotePlaylist | None:
        try:
            async with self._client() as client:
                playlist = await client.request_json(
                    "GET",
                    f"playlists/{playlist_id}",
                    params={"fields": "id,external_urls"},
                    headers={"Authorization": f"Bearer {token}"},
                )
        except ProviderError as error:
            if error.status_code == 404:
                return None
            raise self._translate(error) from error
        return self._remote(playlist)

    async def find_playlist(
        self, token: str, account_id: str, marker: str, spend: Spend
    ) -> RemotePlaylist | None:
        for page in range(4):
            result = await self._api(
                token, "GET", "me/playlists", params={"limit": PAGE, "offset": page * PAGE}
            )
            for playlist in (result or {}).get("items") or []:
                if playlist and marker in str(playlist.get("description") or ""):
                    return self._remote(playlist)
            if not (result or {}).get("next"):
                break
        return None

    async def create_playlist(
        self, token: str, name: str, description: str, spend: Spend
    ) -> RemotePlaylist:
        playlist = await self._api(
            token,
            "POST",
            "me/playlists",
            json={"name": name, "description": description, "public": False},
        )
        return self._remote(playlist)

    async def replace_items(
        self, token: str, playlist_id: str, item_ids: Sequence[str], spend: Spend
    ) -> None:
        # PUT replaces the whole list (idempotent); later batches append to it.
        await self._api(
            token,
            "PUT",
            f"playlists/{playlist_id}/items",
            json={"uris": list(item_ids[:ITEMS_PER_CALL])},
        )
        for start in range(ITEMS_PER_CALL, len(item_ids), ITEMS_PER_CALL):
            await self._api(
                token,
                "POST",
                f"playlists/{playlist_id}/items",
                json={"uris": list(item_ids[start : start + ITEMS_PER_CALL])},
            )
