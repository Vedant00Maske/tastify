"""TASTIFY users, their interaction events, declared preferences and derived taste profiles
(docs/DATABASE.md, ADR-016).

- `user_interactions` are immutable facts (spec §6.4 rule 7): never updated, only appended.
  `client_event_id` makes ingestion idempotent: a retried batch does not record events twice.
- Preferences are relational (one row per declared artist or genre), so they are validated by
  foreign keys and queried without parsing JSON.
- `user_taste_profiles` is a derived, recomputable snapshot (rule 8: raw events separate from
  aggregated features). Its maps are JSONB because they are always read and written whole, bounded
  in size (at most 50 entries), and rebuilt from events whenever the events or models change.

Research listening data (ListenBrainz) never enters these tables (DATA_SOURCES.md, Privacy).
Credentials (Milestone 4): the e-mail is stored lower-cased and unique; the password only as an
Argon2id hash (app.domains.auth.passwords). Sessions live in `user_sessions` (ADR-017).
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.catalogue.models import created_at_column, updated_at_column, uuid_pk
from app.domains.recommendations.models import EMBEDDING_DIMENSIONS
from app.domains.users.events import EVENT_TYPES
from app.domains.users.profile import ExplorationMode

USER_STATUSES = ("active", "deleted")
PREFERENCES = ("preferred", "excluded")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(_in("status", USER_STATUSES), name="status_valid"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"))
    # Terms and privacy acknowledgement at registration (spec §12.4, consent).
    terms_accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class UserSession(Base):
    """A login session. The browser holds an opaque random token in an HttpOnly cookie; only
    its SHA-256 is stored, so a database leak does not reveal usable tokens."""

    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(256))


class UserPreference(Base):
    """Scalar settings. A missing row means defaults (automatic exploration, personalization on)."""

    __tablename__ = "user_preferences"
    __table_args__ = (
        CheckConstraint(
            _in("exploration_mode", tuple(m.value for m in ExplorationMode)),
            name="exploration_mode_valid",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # NULL: derived from the user's behaviour (TasteProfile.discovery_target).
    exploration_mode: Mapped[str | None] = mapped_column(String(16))
    # Personalization opt-out (spec §12.4): when false, recommendations ignore the user's data.
    personalization_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # Favourite mood mixes (keys of app.domains.recommendations.moods.MOODS), in order.
    preferred_moods: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), server_default=text("'{}'::varchar[]")
    )
    updated_at: Mapped[datetime] = updated_at_column()


class UserArtistPreference(Base):
    __tablename__ = "user_artist_preferences"
    __table_args__ = (CheckConstraint(_in("preference", PREFERENCES), name="preference_valid"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    artist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    preference: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = created_at_column()


class UserGenrePreference(Base):
    __tablename__ = "user_genre_preferences"
    __table_args__ = (CheckConstraint(_in("preference", PREFERENCES), name="preference_valid"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    preference: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = created_at_column()


class UserInteraction(Base):
    """One immutable interaction event."""

    __tablename__ = "user_interactions"
    __table_args__ = (
        CheckConstraint(_in("event_type", EVENT_TYPES), name="event_type_valid"),
        CheckConstraint("position_ms IS NULL OR position_ms >= 0", name="position_valid"),
        UniqueConstraint("user_id", "client_event_id", name="uq_user_interactions_client_event"),
        Index("ix_user_interactions_user_id_occurred_at", "user_id", "occurred_at"),
        Index("ix_user_interactions_track_id_event_type", "track_id", "event_type"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # RESTRICT: catalogue tracks are not deleted while events reference them.
    track_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracks.id", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(String(16))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column()
    source: Mapped[str] = mapped_column(String(32), server_default=text("'app'"))
    # Playback position when the event happened (how early a skip was).
    position_ms: Mapped[int | None] = mapped_column(Integer)
    # Client-generated id; retries with the same id are ignored.
    client_event_id: Mapped[str | None] = mapped_column(String(64))


class UserTasteProfile(Base):
    """Derived taste profile (app.domains.users.profile.TasteProfile), rebuilt from events."""

    __tablename__ = "user_taste_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    profile_version: Mapped[str] = mapped_column(String(64))
    # The content model whose embeddings built the profile; a new model triggers a rebuild.
    content_model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_versions.id", ondelete="SET NULL")
    )
    long_term_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    short_term_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    genre_affinity: Mapped[dict[str, float]] = mapped_column(JSONB)
    artist_affinity: Mapped[dict[str, float]] = mapped_column(JSONB)
    negative_artists: Mapped[dict[str, float]] = mapped_column(JSONB)
    known_artists: Mapped[list[str]] = mapped_column(JSONB)
    seed_tracks: Mapped[list[str]] = mapped_column(JSONB)
    recent_tracks: Mapped[list[str]] = mapped_column(JSONB)
    listening_stats: Mapped[dict[str, Any]] = mapped_column(JSONB)
    exploration_preference: Mapped[float] = mapped_column(Float)
    history_size: Mapped[int] = mapped_column(Integer)
    interaction_count: Mapped[int] = mapped_column(Integer)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Reference time of the decays.
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = updated_at_column()
