"""The provider interface (spec §10.1, ADR-006): one adapter per music platform, with declared
capabilities instead of assuming every platform can do everything.

Adapters only talk to their platform and translate its data and errors. Tokens, the database,
quotas and retries across operations belong to `IntegrationService`.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

import httpx

from app.domains.integrations.clients.base import ProviderError


class Capability(StrEnum):
    IMPORT_HISTORY = "import_history"
    EXPORT_PLAYLIST = "export_playlist"
    SEARCH_TRACKS = "search_tracks"


class AuthKind(StrEnum):
    TOKEN = "token"  # noqa: S105 - an auth kind, not a secret (ListenBrainz personal token)
    OAUTH = "oauth"  # authorization code with PKCE (Spotify, YouTube)
    NONE = "none"  # public data only (MusicBrainz)


# --- errors -----------------------------------------------------------------------------------


class IntegrationError(RuntimeError):
    """Base class: a provider operation could not be completed."""


class ProviderNotConfiguredError(IntegrationError):
    """This server has no credentials for the provider (e.g. no Spotify client id)."""


class NotSupportedError(IntegrationError):
    """The provider does not offer this capability."""


class InvalidCredentialsError(IntegrationError):
    """The token or authorization code the user supplied was rejected."""


class ProviderAuthError(IntegrationError):
    """The stored authorization no longer works (revoked or expired): reconnect."""


class ProviderRejectedError(IntegrationError):
    """The provider refused the request (permissions, account limits, invalid data)."""


class ProviderUnavailableError(IntegrationError):
    """The provider failed or could not be reached; trying again later may work."""


class ProviderRateLimitedError(IntegrationError):
    def __init__(self, provider: str, retry_after: float | None) -> None:
        super().__init__(f"{provider} is rate limiting requests")
        self.retry_after = retry_after


class QuotaExceededError(IntegrationError):
    def __init__(self, provider: str, needed: int | None = None, remaining: int | None = None):
        detail = f" (needs about {needed} units, {remaining} left today)" if needed else ""
        super().__init__(f"the daily {provider} API quota is used up{detail}")
        self.needed = needed
        self.remaining = remaining


def translate(provider: str, error: ProviderError) -> IntegrationError:
    """Map an HTTP failure to the error the service and API understand."""
    status = error.status_code
    if status is None or status >= 500:
        return ProviderUnavailableError(f"{provider} is unavailable right now")
    if status == 401:
        return ProviderAuthError(f"{provider} no longer accepts SONIQUEO's access")
    if status == 429:
        return ProviderRateLimitedError(provider, error.retry_after)
    return ProviderRejectedError(f"{provider} refused the request (HTTP {status})")


# --- data -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Account:
    """The result of connecting: who the user is on the provider, and the credentials."""

    external_user_id: str
    external_name: str | None
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExternalItem:
    """One imported fact: a listen ("play") or a liked / saved track ("like")."""

    key: str  # stable per provider: re-importing the same item is a no-op
    event_type: str
    occurred_at: datetime
    artist: str
    title: str
    recording_mbid: str | None = None
    isrc: str | None = None


@dataclass
class ImportBatch:
    items: list[ExternalItem] = field(default_factory=list)
    cursor: str | None = None  # where the next incremental import continues
    complete: bool = True  # False when the bounded import stopped before the oldest item


@dataclass(frozen=True)
class ExportTrack:
    track_id: str
    title: str
    artist: str
    recording_mbid: str | None
    isrc: str | None


@dataclass(frozen=True)
class RemotePlaylist:
    id: str
    url: str | None


@dataclass(frozen=True)
class ExternalRecording:
    mbid: str
    title: str
    artist: str
    release: str | None
    length_ms: int | None
    url: str


Spend = Callable[[int], Awaitable[None]]  # reserve quota units before a call


async def no_quota(_units: int) -> None:
    return None


class MusicProvider:
    """Base adapter. Every operation a provider does not support raises NotSupportedError."""

    name: str = ""
    display_name: str = ""
    auth: AuthKind = AuthKind.NONE
    capabilities: frozenset[Capability] = frozenset()
    #: Tracks per export (YouTube's quota allows only small exports).
    max_export_tracks: int = 500

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    def available(self) -> bool:
        """Whether this server is configured to use the provider."""
        return True

    # --- connecting
    async def connect_with_token(self, token: str) -> Account:
        raise NotSupportedError(f"{self.name} does not use personal tokens")

    def authorization_url(self, state: str, code_challenge: str, redirect_uri: str) -> str:
        raise NotSupportedError(f"{self.name} does not use OAuth")

    async def exchange_code(self, code: str, code_verifier: str, redirect_uri: str) -> Account:
        raise NotSupportedError(f"{self.name} does not use OAuth")

    async def refresh(self, refresh_token: str) -> Account:
        raise ProviderAuthError(f"{self.name} tokens cannot be refreshed")

    async def revoke(self, token: str) -> None:
        """Best effort: ask the provider to forget the grant."""
        return None

    # --- importing
    async def fetch_history(self, token: str, account_id: str, cursor: str | None) -> ImportBatch:
        raise NotSupportedError(f"{self.name} cannot import history")

    # --- exporting
    def export_cost(self, tracks: int, unresolved: int, existing_playlist: bool) -> int:
        """Quota units an export may use at most (0 where there is no unit quota)."""
        return 0

    async def resolve_track(self, token: str, track: ExportTrack, spend: Spend) -> str | None:
        raise NotSupportedError(f"{self.name} cannot export playlists")

    async def get_playlist(
        self, token: str, playlist_id: str, spend: Spend
    ) -> RemotePlaylist | None:
        raise NotSupportedError(f"{self.name} cannot export playlists")

    async def find_playlist(
        self, token: str, account_id: str, marker: str, spend: Spend
    ) -> RemotePlaylist | None:
        raise NotSupportedError(f"{self.name} cannot export playlists")

    async def create_playlist(
        self, token: str, name: str, description: str, spend: Spend
    ) -> RemotePlaylist:
        raise NotSupportedError(f"{self.name} cannot export playlists")

    async def replace_items(
        self, token: str, playlist_id: str, item_ids: Sequence[str], spend: Spend
    ) -> None:
        raise NotSupportedError(f"{self.name} cannot export playlists")

    # --- catalogue
    async def search_recordings(self, query: str, limit: int) -> list[ExternalRecording]:
        raise NotSupportedError(f"{self.name} cannot search")
