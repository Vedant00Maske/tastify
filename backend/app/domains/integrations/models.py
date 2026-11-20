"""Connections to music platforms, history imports, playlist exports and provider track ids
(Milestone 5; DATABASE.md, ADR-018).

Access and refresh tokens are stored only encrypted (AES-256-GCM, `tokens.py`), bound to their
user and provider. Every table is owned by a user or a playlist and is deleted with it.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.catalogue.models import created_at_column, updated_at_column, uuid_pk

PROVIDERS = ("listenbrainz", "spotify", "youtube")
CONNECTION_STATUSES = ("active", "reauth_required")
RUN_STATUSES = ("running", "completed", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class ProviderConnection(Base):
    """A user's linked account on a provider: at most one per provider."""

    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider"),
        CheckConstraint(_in("provider", PROVIDERS), name="provider_valid"),
        CheckConstraint(_in("status", CONNECTION_STATUSES), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    external_user_id: Mapped[str] = mapped_column(String(255))
    external_name: Mapped[str | None] = mapped_column(String(255))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(128)), server_default="{}")
    # "v1:" + base64(nonce || ciphertext || tag); never returned by the API or the data export.
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), server_default="active")
    # Provider-specific resume point for incremental imports (e.g. the newest listen imported).
    import_cursor: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(String(500))
    connected_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class ProviderImport(Base):
    """One run of importing listening history or library data from a provider."""

    __tablename__ = "provider_imports"
    __table_args__ = (
        CheckConstraint(_in("provider", PROVIDERS), name="provider_valid"),
        CheckConstraint(_in("status", RUN_STATUSES), name="status_valid"),
        Index("ix_provider_imports_user_id_started_at", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    fetched: Mapped[int] = mapped_column(Integer, server_default="0")
    matched: Mapped[int] = mapped_column(Integer, server_default="0")
    imported: Mapped[int] = mapped_column(Integer, server_default="0")
    duplicates: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime] = created_at_column()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlaylistExport(Base):
    """A SONIQUEO playlist mirrored on a provider. One row per (playlist, provider): exporting
    again updates the same remote playlist instead of creating another (retry-safe)."""

    __tablename__ = "playlist_exports"
    __table_args__ = (
        UniqueConstraint("playlist_id", "provider"),
        CheckConstraint(_in("provider", PROVIDERS), name="provider_valid"),
        CheckConstraint(_in("status", RUN_STATUSES), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    playlist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    external_playlist_id: Mapped[str | None] = mapped_column(String(255))
    external_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16))
    exported: Mapped[int] = mapped_column(Integer, server_default="0")
    unmatched: Mapped[int] = mapped_column(Integer, server_default="0")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderTrackId(Base):
    """A provider's id for a catalogue track, found by searching the provider (Spotify by ISRC,
    YouTube by artist and title). Cached so an export does not search again; re-checked after
    `fetched_at` ages out (YouTube's developer policies limit how long API data is kept).
    `external_id` NULL records "searched, not found"."""

    __tablename__ = "provider_track_ids"
    __table_args__ = (CheckConstraint(_in("provider", PROVIDERS), name="provider_valid"),)

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    fetched_at: Mapped[datetime] = created_at_column()
