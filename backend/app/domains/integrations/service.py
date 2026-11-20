"""Connecting accounts, importing history and exporting playlists (Milestone 5; ADR-018).

Isolation: every provider call goes through an adapter that turns provider failures into
`IntegrationError`s; nothing outside this module depends on a provider being up.
Tokens: encrypted at rest (`tokens.py`), refreshed shortly before they expire and once more
when the provider rejects them; a connection that cannot be refreshed is marked
`reauth_required` instead of failing repeatedly.
Exports: one `playlist_exports` row per playlist and provider remembers the remote playlist,
which is created at most once (looked up again by a marker in its description if the id was
lost) and then made equal to the SONIQUEO playlist, so retrying an export is always safe.
"""

import base64
import hashlib
import json
import logging
import secrets
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domains.catalogue.models import Artist, Track, TrackExternalId
from app.domains.integrations import tokens
from app.domains.integrations.matching import match_items
from app.domains.integrations.models import (
    PlaylistExport,
    ProviderConnection,
    ProviderImport,
    ProviderTrackId,
)
from app.domains.integrations.providers.base import (
    Account,
    AuthKind,
    Capability,
    ExportTrack,
    IntegrationError,
    InvalidCredentialsError,
    MusicProvider,
    NotSupportedError,
    ProviderAuthError,
    ProviderNotConfiguredError,
    Spend,
    no_quota,
)
from app.domains.integrations.providers.listenbrainz import ListenBrainzProvider
from app.domains.integrations.providers.musicbrainz import MusicBrainzProvider
from app.domains.integrations.providers.spotify import SpotifyProvider
from app.domains.integrations.providers.youtube import YouTubeProvider
from app.domains.integrations.quota import QuotaMeter
from app.domains.integrations.schemas import (
    ConnectionOut,
    ExportOut,
    ImportOut,
    ProviderList,
    ProviderOut,
    RecordingOut,
    RecordingSearchOut,
)
from app.domains.playlists.models import Playlist, PlaylistTrack
from app.domains.playlists.service import PlaylistNotFoundError
from app.domains.users.models import UserInteraction
from app.domains.users.repository import UserRepository
from app.domains.users.service import TasteProfileService

logger = logging.getLogger(__name__)
T = TypeVar("T")

OAUTH_STATE_TTL = 600  # seconds to finish signing in at the provider
REFRESH_MARGIN = timedelta(seconds=60)
TRACK_ID_MAX_AGE = timedelta(days=30)  # YouTube developer policies: refresh stored API data
EVENT_CHUNK = 1000
EVENT_PREFIX = {"listenbrainz": "lb", "spotify": "sp", "youtube": "yt"}

DESCRIPTIONS = {
    "listenbrainz": "Import your listening history and export playlists as private "
    "ListenBrainz playlists. Connect with your ListenBrainz user token.",
    "spotify": "Import your saved and recently played tracks, and export playlists to your "
    "Spotify library.",
    "youtube": "Export playlists as private YouTube playlists (up to 50 tracks; YouTube's API "
    "quota is small).",
    "musicbrainz": "Open music encyclopedia behind the SONIQUEO catalogue. Used to find "
    "recordings SONIQUEO does not have yet; no account needed.",
}
ORDER = ("listenbrainz", "spotify", "youtube", "musicbrainz")


class UnknownProviderError(IntegrationError):
    pass


class NotConnectedError(IntegrationError):
    pass


class ConsentRequiredError(IntegrationError):
    pass


class OAuthStateError(IntegrationError):
    """The sign-in at the provider expired, was already used, or belongs to someone else."""


def default_providers() -> dict[str, MusicProvider]:
    adapters: list[MusicProvider] = [
        ListenBrainzProvider(),
        SpotifyProvider(),
        YouTubeProvider(),
        MusicBrainzProvider(),
    ]
    return {adapter.name: adapter for adapter in adapters}


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, S256 code_challenge) per RFC 7636."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def event_id(provider: str, key: str) -> str:
    """A stable idempotency key for an imported item (fits client_event_id's 64 characters)."""
    return f"{EVENT_PREFIX[provider]}:{hashlib.sha256(key.encode()).hexdigest()[:56]}"


def export_marker(playlist_id: uuid.UUID) -> str:
    return f"[soniqueo:{playlist_id}]"


def _import_out(run: ProviderImport) -> ImportOut:
    return ImportOut(
        id=run.id,
        provider=run.provider,
        status=run.status,
        fetched=run.fetched,
        matched=run.matched,
        imported=run.imported,
        duplicates=run.duplicates,
        error=run.error,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _export_out(record: PlaylistExport) -> ExportOut:
    return ExportOut(
        provider=record.provider,
        status=record.status,
        external_url=record.external_url,
        exported=record.exported,
        unmatched=record.unmatched,
        attempts=record.attempts,
        error=record.error,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


class IntegrationService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis,
        providers: dict[str, MusicProvider] | None = None,
    ) -> None:
        self.session = session
        self.redis = redis
        self.providers = providers if providers is not None else default_providers()

    # --- lookups ------------------------------------------------------------------------------

    def _adapter(self, provider: str, capability: Capability | None = None) -> MusicProvider:
        adapter = self.providers.get(provider)
        if adapter is None:
            raise UnknownProviderError(f"unknown provider {provider!r}")
        if not adapter.available():
            raise ProviderNotConfiguredError(f"{adapter.display_name} is not configured here")
        if capability is not None and capability not in adapter.capabilities:
            raise NotSupportedError(f"{adapter.display_name} does not support {capability.value}")
        return adapter

    async def _connection(self, user_id: uuid.UUID, provider: str) -> ProviderConnection:
        connection = await self.session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.user_id == user_id, ProviderConnection.provider == provider
            )
        )
        if connection is None:
            raise NotConnectedError(f"connect {provider} first")
        return connection

    async def _last_imports(self, user_id: uuid.UUID) -> dict[str, ProviderImport]:
        runs = (
            await self.session.scalars(
                select(ProviderImport)
                .where(ProviderImport.user_id == user_id)
                .order_by(ProviderImport.started_at.desc())
                .limit(50)
            )
        ).all()
        latest: dict[str, ProviderImport] = {}
        for run in runs:
            latest.setdefault(run.provider, run)
        return latest

    async def overview(self, user_id: uuid.UUID) -> ProviderList:
        connections = {
            c.provider: c
            for c in (
                await self.session.scalars(
                    select(ProviderConnection).where(ProviderConnection.user_id == user_id)
                )
            ).all()
        }
        latest = await self._last_imports(user_id)
        providers = []
        for name in ORDER:
            adapter = self.providers.get(name)
            if adapter is None:
                continue
            connection = connections.get(name)
            providers.append(
                ProviderOut(
                    provider=name,
                    name=adapter.display_name,
                    description=DESCRIPTIONS.get(name, ""),
                    auth=adapter.auth.value,
                    capabilities=sorted(c.value for c in adapter.capabilities),
                    available=adapter.available(),
                    max_export_tracks=adapter.max_export_tracks,
                    connection=ConnectionOut(
                        status=connection.status,
                        external_name=connection.external_name,
                        scopes=list(connection.scopes or []),
                        connected_at=connection.connected_at,
                        last_import=_import_out(latest[name]) if name in latest else None,
                    )
                    if connection
                    else None,
                )
            )
        return ProviderList(providers=providers, tokens_configured=tokens.configured())

    # --- connecting ---------------------------------------------------------------------------

    async def _store(self, user_id: uuid.UUID, provider: str, account: Account) -> None:
        cipher = tokens.TokenCipher.from_settings()
        connection = await self.session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.user_id == user_id, ProviderConnection.provider == provider
            )
        )
        if connection is None:
            connection = ProviderConnection(user_id=user_id, provider=provider)
            self.session.add(connection)
        elif connection.external_user_id != account.external_user_id:
            # Another account on the same provider: its import position does not carry over.
            connection.import_cursor = None
        connection.external_user_id = account.external_user_id
        connection.external_name = account.external_name
        connection.scopes = list(account.scopes)
        connection.access_token = cipher.encrypt(account.access_token, user_id, provider)
        connection.refresh_token = (
            cipher.encrypt(account.refresh_token, user_id, provider)
            if account.refresh_token
            else None
        )
        connection.token_expires_at = account.expires_at
        connection.status = "active"
        connection.last_error = None
        await self.session.commit()
        logger.info("provider connected user=%s provider=%s", user_id, provider)

    async def connect_token(self, user_id: uuid.UUID, provider: str, token: str) -> ProviderList:
        adapter = self._adapter(provider)
        if adapter.auth is not AuthKind.TOKEN:
            raise NotSupportedError(f"{adapter.display_name} connects with OAuth")
        tokens.TokenCipher.from_settings()  # fail before calling the provider without a key
        account = await adapter.connect_with_token(token.strip())
        await self._store(user_id, provider, account)
        return await self.overview(user_id)

    async def authorize(self, user_id: uuid.UUID, provider: str) -> str:
        adapter = self._adapter(provider)
        if adapter.auth is not AuthKind.OAUTH:
            raise NotSupportedError(f"{adapter.display_name} does not use OAuth")
        tokens.TokenCipher.from_settings()
        state = secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        await self.redis.set(
            f"oauth:{state}",
            json.dumps({"user": str(user_id), "provider": provider, "verifier": verifier}),
            ex=OAUTH_STATE_TTL,
        )
        return adapter.authorization_url(state, challenge, get_settings().redirect_uri(provider))

    async def complete_oauth(
        self, user_id: uuid.UUID, provider: str, code: str, state: str
    ) -> None:
        adapter = self._adapter(provider)
        raw = await self.redis.getdel(f"oauth:{state}")  # single use
        if not raw:
            raise OAuthStateError("the sign-in expired or was already used; try again")
        saved = json.loads(raw)
        if saved.get("user") != str(user_id) or saved.get("provider") != provider:
            raise OAuthStateError("this sign-in was started by another account")
        account = await adapter.exchange_code(
            code, saved["verifier"], get_settings().redirect_uri(provider)
        )
        await self._store(user_id, provider, account)

    async def disconnect(self, user_id: uuid.UUID, provider: str, delete_imported: bool) -> None:
        adapter = self.providers.get(provider)
        connection = await self._connection(user_id, provider)
        if adapter is not None:
            try:
                token = tokens.TokenCipher.from_settings().decrypt(
                    connection.access_token, user_id, provider
                )
                await adapter.revoke(token)
            except (IntegrationError, tokens.TokenKeyMissingError, tokens.TokenDecryptionError):
                logger.info("revoking %s access failed; deleting the tokens anyway", provider)
        await self.session.delete(connection)
        if delete_imported:
            await self.session.execute(
                delete(UserInteraction).where(
                    UserInteraction.user_id == user_id, UserInteraction.source == provider
                )
            )
            await TasteProfileService(self.session).rebuild(user_id)
        await self.session.commit()
        logger.info(
            "provider disconnected user=%s provider=%s purged=%s",
            user_id,
            provider,
            delete_imported,
        )

    # --- tokens -------------------------------------------------------------------------------

    async def _needs_reauth(self, connection: ProviderConnection, message: str) -> None:
        connection.status = "reauth_required"
        connection.last_error = message[:500]
        await self.session.commit()

    async def _refresh(self, connection: ProviderConnection, adapter: MusicProvider) -> str:
        cipher = tokens.TokenCipher.from_settings()
        if not connection.refresh_token:
            await self._needs_reauth(connection, "access expired")
            raise ProviderAuthError(f"reconnect {adapter.display_name}")
        refresh = cipher.decrypt(connection.refresh_token, connection.user_id, connection.provider)
        try:
            account = await adapter.refresh(refresh)
        except (InvalidCredentialsError, ProviderAuthError) as error:
            await self._needs_reauth(connection, str(error))
            raise ProviderAuthError(f"reconnect {adapter.display_name}") from error
        connection.access_token = cipher.encrypt(
            account.access_token, connection.user_id, connection.provider
        )
        if account.refresh_token:
            connection.refresh_token = cipher.encrypt(
                account.refresh_token, connection.user_id, connection.provider
            )
        connection.token_expires_at = account.expires_at
        await self.session.commit()
        return account.access_token

    async def _authorized(
        self,
        connection: ProviderConnection,
        adapter: MusicProvider,
        operation: Callable[[str], Awaitable[T]],
    ) -> T:
        if connection.status == "reauth_required":
            raise ProviderAuthError(f"reconnect {adapter.display_name}")
        cipher = tokens.TokenCipher.from_settings()
        try:
            token = cipher.decrypt(connection.access_token, connection.user_id, connection.provider)
        except tokens.TokenDecryptionError as error:
            await self._needs_reauth(connection, "stored access cannot be read")
            raise ProviderAuthError(f"reconnect {adapter.display_name}") from error
        expires = connection.token_expires_at
        if expires is not None and expires - datetime.now(UTC) < REFRESH_MARGIN:
            token = await self._refresh(connection, adapter)
        try:
            return await operation(token)
        except ProviderAuthError:
            if adapter.auth is not AuthKind.OAUTH:
                await self._needs_reauth(connection, "the provider rejected the token")
                raise
            token = await self._refresh(connection, adapter)
            try:
                return await operation(token)
            except ProviderAuthError:
                await self._needs_reauth(connection, "the provider rejected the token")
                raise

    # --- importing ----------------------------------------------------------------------------

    async def import_history(self, user_id: uuid.UUID, provider: str, consent: bool) -> ImportOut:
        if not consent:
            raise ConsentRequiredError("importing listening history needs your consent")
        adapter = self._adapter(provider, Capability.IMPORT_HISTORY)
        connection = await self._connection(user_id, provider)
        run = ProviderImport(user_id=user_id, provider=provider, status="running")
        self.session.add(run)
        await self.session.commit()
        try:
            batch = await self._authorized(
                connection,
                adapter,
                lambda token: adapter.fetch_history(
                    token, connection.external_user_id, connection.import_cursor
                ),
            )
        except IntegrationError as error:
            run.status, run.error, run.finished_at = "failed", str(error)[:500], datetime.now(UTC)
            await self.session.commit()
            raise

        tracks = await match_items(self.session, batch.items)
        rows = [
            {
                "user_id": user_id,
                "track_id": track,
                "event_type": item.event_type,
                "occurred_at": item.occurred_at,
                "source": provider,
                "client_event_id": event_id(provider, item.key),
            }
            for item, track in zip(batch.items, tracks, strict=True)
            if track is not None
        ]
        users = UserRepository(self.session)
        imported = 0
        for start in range(0, len(rows), EVENT_CHUNK):
            imported += await users.insert_events(rows[start : start + EVENT_CHUNK])
        run.fetched, run.matched, run.imported = len(batch.items), len(rows), imported
        run.duplicates = len(rows) - imported
        run.status, run.finished_at = "completed", datetime.now(UTC)
        connection.import_cursor = batch.cursor
        connection.last_error = None
        if imported:
            await TasteProfileService(self.session).rebuild(user_id)
        await self.session.commit()
        await self.session.refresh(run)  # server-side timestamps
        logger.info(
            "history imported user=%s provider=%s fetched=%d matched=%d imported=%d",
            user_id,
            provider,
            run.fetched,
            run.matched,
            imported,
        )
        return _import_out(run)

    async def imports(self, user_id: uuid.UUID) -> list[ImportOut]:
        runs = (
            await self.session.scalars(
                select(ProviderImport)
                .where(ProviderImport.user_id == user_id)
                .order_by(ProviderImport.started_at.desc())
                .limit(20)
            )
        ).all()
        return [_import_out(r) for r in runs]

    # --- exporting ----------------------------------------------------------------------------

    async def _playlist(self, user_id: uuid.UUID, playlist_id: uuid.UUID) -> Playlist:
        playlist = await self.session.scalar(
            select(Playlist).where(Playlist.id == playlist_id, Playlist.user_id == user_id)
        )
        if playlist is None:
            raise PlaylistNotFoundError()
        return playlist

    async def _export_tracks(self, playlist_id: uuid.UUID, limit: int) -> list[ExportTrack]:
        rows = await self.session.execute(
            select(Track.id, Track.title, Artist.name, Track.isrc)
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
            .join(Artist, Artist.id == Track.artist_id)
            .where(PlaylistTrack.playlist_id == playlist_id)
            .order_by(PlaylistTrack.position)
            .limit(limit)
        )
        listed = rows.all()
        mbids = dict(
            (
                await self.session.execute(
                    select(TrackExternalId.track_id, TrackExternalId.external_id).where(
                        TrackExternalId.track_id.in_([r[0] for r in listed]),
                        TrackExternalId.provider == "musicbrainz",
                    )
                )
            ).all()
        )
        return [
            ExportTrack(
                track_id=str(track_id),
                title=title,
                artist=artist,
                recording_mbid=mbids.get(track_id),
                isrc=isrc,
            )
            for track_id, title, artist, isrc in listed
        ]

    async def _cached_ids(
        self, provider: str, tracks: Sequence[ExportTrack]
    ) -> dict[str, str | None]:
        if provider == "listenbrainz":
            return {}
        fresh_after = datetime.now(UTC) - TRACK_ID_MAX_AGE
        rows = await self.session.execute(
            select(ProviderTrackId.track_id, ProviderTrackId.external_id).where(
                ProviderTrackId.provider == provider,
                ProviderTrackId.track_id.in_([uuid.UUID(t.track_id) for t in tracks]),
                ProviderTrackId.fetched_at > fresh_after,
            )
        )
        return {str(track): external for track, external in rows.all()}

    async def _resolve(
        self,
        adapter: MusicProvider,
        token: str,
        tracks: Sequence[ExportTrack],
        spend: Spend,
    ) -> tuple[list[str], int]:
        cached = await self._cached_ids(adapter.name, tracks)
        found: list[str] = []
        unmatched = 0
        for track in tracks:
            if track.track_id in cached:
                external = cached[track.track_id]
            else:
                external = await adapter.resolve_track(token, track, spend)
                if adapter.name != "listenbrainz":
                    await self.session.execute(
                        insert(ProviderTrackId)
                        .values(
                            provider=adapter.name,
                            track_id=uuid.UUID(track.track_id),
                            external_id=external,
                            fetched_at=datetime.now(UTC),
                        )
                        .on_conflict_do_update(
                            index_elements=["provider", "track_id"],
                            set_={"external_id": external, "fetched_at": datetime.now(UTC)},
                        )
                    )
                    await self.session.commit()  # keep paid-for lookups even if a later call fails
            if external:
                found.append(external)
            else:
                unmatched += 1
        return found, unmatched

    async def export_playlist(
        self, user_id: uuid.UUID, playlist_id: uuid.UUID, provider: str
    ) -> ExportOut:
        adapter = self._adapter(provider, Capability.EXPORT_PLAYLIST)
        playlist = await self._playlist(user_id, playlist_id)
        connection = await self._connection(user_id, provider)
        tracks = await self._export_tracks(playlist.id, adapter.max_export_tracks)

        record = await self.session.scalar(
            select(PlaylistExport).where(
                PlaylistExport.playlist_id == playlist.id, PlaylistExport.provider == provider
            )
        )
        if record is None:
            record = PlaylistExport(playlist_id=playlist.id, provider=provider, attempts=0)
            self.session.add(record)
        record.status, record.error = "running", None
        record.attempts = (record.attempts or 0) + 1
        await self.session.commit()

        meter: QuotaMeter | None = None
        spend: Spend = no_quota
        if provider == "youtube":
            meter = QuotaMeter(self.redis, provider, get_settings().youtube_daily_quota)
            spend = meter.spend
        marker = export_marker(playlist.id)
        description = " ".join(
            part
            for part in ("Exported from SONIQUEO.", (playlist.description or "").strip(), marker)
            if part
        )

        async def run(token: str) -> tuple[list[str], int]:
            if meter is not None:
                cached = await self._cached_ids(provider, tracks)
                await meter.require(
                    adapter.export_cost(
                        len(tracks),
                        sum(1 for t in tracks if t.track_id not in cached),
                        record.external_playlist_id is not None,
                    )
                )
            ids, unmatched = await self._resolve(adapter, token, tracks, spend)
            remote = None
            if record.external_playlist_id:
                remote = await adapter.get_playlist(token, record.external_playlist_id, spend)
            if remote is None:
                remote = await adapter.find_playlist(
                    token, connection.external_user_id, marker, spend
                )
            if remote is None:
                remote = await adapter.create_playlist(token, playlist.name, description, spend)
            # Remember it before filling it: a failure from here on is retried on the same one.
            record.external_playlist_id, record.external_url = remote.id, remote.url
            await self.session.commit()
            await adapter.replace_items(token, remote.id, ids, spend)
            return ids, unmatched

        try:
            ids, unmatched = await self._authorized(connection, adapter, run)
        except IntegrationError as error:
            record.status, record.error = "failed", str(error)[:500]
            await self.session.commit()
            raise
        record.status, record.exported, record.unmatched = "completed", len(ids), unmatched
        record.completed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(record)  # server-side updated_at
        logger.info(
            "playlist exported user=%s playlist=%s provider=%s tracks=%d unmatched=%d",
            user_id,
            playlist.id,
            provider,
            len(ids),
            unmatched,
        )
        return _export_out(record)

    async def exports(self, user_id: uuid.UUID, playlist_id: uuid.UUID) -> list[ExportOut]:
        playlist = await self._playlist(user_id, playlist_id)
        records = (
            await self.session.scalars(
                select(PlaylistExport)
                .where(PlaylistExport.playlist_id == playlist.id)
                .order_by(PlaylistExport.provider)
            )
        ).all()
        return [_export_out(r) for r in records]

    # --- MusicBrainz --------------------------------------------------------------------------

    async def search_musicbrainz(self, query: str, limit: int) -> RecordingSearchOut:
        adapter = self._adapter("musicbrainz", Capability.SEARCH_TRACKS)
        found = await adapter.search_recordings(query, limit)
        known = dict(
            (
                await self.session.execute(
                    select(TrackExternalId.external_id, TrackExternalId.track_id).where(
                        TrackExternalId.provider == "musicbrainz",
                        TrackExternalId.external_id.in_([r.mbid for r in found]),
                    )
                )
            ).all()
            if found
            else []
        )
        return RecordingSearchOut(
            query=query,
            results=[
                RecordingOut(
                    mbid=r.mbid,
                    title=r.title,
                    artist=r.artist,
                    release=r.release,
                    length_ms=r.length_ms,
                    url=r.url,
                    track_id=known.get(r.mbid),
                )
                for r in found
            ],
        )
