"""Catalogue schema: canonical tracks, artists, albums and genres, their identifiers in every
provider, optional audio features, and the provenance of every ingested record (docs/DATABASE.md).

Design rules (spec §6.4): UUID keys, enforced foreign keys, unique provider identifiers, UTC
timestamps, and JSONB only for genuinely variable data (raw source payloads, job statistics,
match evidence).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

UUID_DEFAULT = text("gen_random_uuid()")


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, server_default=UUID_DEFAULT)


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def updated_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


def source_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("data_sources.id", ondelete="RESTRICT"), index=True)


# --- Provenance ------------------------------------------------------------------------------


class DataSource(Base):
    """An external dataset or API, with the licence terms that travel with its records."""

    __tablename__ = "data_sources"
    __table_args__ = (
        CheckConstraint(
            "usage_restriction IN ('none', 'non_commercial', 'research_only')",
            name="usage_restriction_valid",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(Text)
    homepage_url: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    license_url: Mapped[str] = mapped_column(Text)
    usage_restriction: Mapped[str] = mapped_column(String(32))
    attribution: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class IngestionJob(Base):
    """One run of one pipeline stage against one source."""

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="status_valid"),
        Index("ix_ingestion_jobs_source_id_started_at", "source_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_sources.id", ondelete="RESTRICT"))
    stage: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), server_default="running")
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = created_at_column()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionError(Base):
    """A record rejected or flagged by a pipeline stage. Kept for data quality reporting."""

    __tablename__ = "ingestion_errors"
    __table_args__ = (Index("ix_ingestion_errors_job_id_error_code", "job_id", "error_code"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_jobs.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str] = mapped_column(String(64))
    record_ref: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()


class RawRecord(Base):
    """A source record exactly as received (API response), for provenance and reprocessing."""

    __tablename__ = "raw_records"
    __table_args__ = (UniqueConstraint("source_id", "entity_type", "external_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_sources.id", ondelete="RESTRICT"))
    entity_type: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion_jobs.id", ondelete="SET NULL")
    )
    fetched_at: Mapped[datetime] = created_at_column()


# --- Canonical catalogue ---------------------------------------------------------------------


class Artist(Base):
    __tablename__ = "artists"
    __table_args__ = (
        Index("ix_artists_name", "name"),
        Index(
            "ix_artists_normalized_name_trgm",
            "normalized_name",
            postgresql_using="gin",
            postgresql_ops={"normalized_name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text)
    artist_type: Mapped[str | None] = mapped_column(String(32))
    area: Mapped[str | None] = mapped_column(Text)
    begin_year: Mapped[int | None] = mapped_column(SmallInteger)
    source_id: Mapped[uuid.UUID] = source_fk()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    external_ids: Mapped[list["ArtistExternalId"]] = relationship(
        back_populates="artist", cascade="all, delete-orphan"
    )


class Album(Base):
    """An album as a work (MusicBrainz release group), independent of editions."""

    __tablename__ = "albums"
    __table_args__ = (Index("ix_albums_primary_artist_id", "primary_artist_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text)
    album_type: Mapped[str | None] = mapped_column(String(32))
    release_date: Mapped[date | None] = mapped_column(Date)
    release_year: Mapped[int | None] = mapped_column(SmallInteger)
    primary_artist_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL")
    )
    source_id: Mapped[uuid.UUID] = source_fk()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    external_ids: Mapped[list["AlbumExternalId"]] = relationship(
        back_populates="album", cascade="all, delete-orphan"
    )


class Track(Base):
    """A canonical recording. Provider identifiers live in track_external_ids."""

    __tablename__ = "tracks"
    __table_args__ = (
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms BETWEEN 1000 AND 10800000",
            name="duration_plausible",
        ),
        CheckConstraint(
            "isrc IS NULL OR isrc ~ '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$'", name="isrc_format"
        ),
        Index("ix_tracks_isrc", "isrc"),
        Index("ix_tracks_artist_id", "artist_id"),
        Index("ix_tracks_album_id", "album_id"),
        Index("ix_tracks_matching_key", "matching_key"),
        Index(
            "ix_tracks_normalized_title_trgm",
            "normalized_title",
            postgresql_using="gin",
            postgresql_ops={"normalized_title": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text)
    # matching_key(primary artist) + "|" + matching_key(clean_title(title)): candidate lookup.
    matching_key: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    release_date: Mapped[date | None] = mapped_column(Date)
    release_year: Mapped[int | None] = mapped_column(SmallInteger)
    isrc: Mapped[str | None] = mapped_column(String(12))
    artist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artists.id", ondelete="RESTRICT"))
    album_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("albums.id", ondelete="SET NULL"))
    source_id: Mapped[uuid.UUID] = source_fk()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    artist: Mapped[Artist] = relationship()
    album: Mapped[Album | None] = relationship()
    credits: Mapped[list["TrackArtist"]] = relationship(
        order_by="TrackArtist.position", cascade="all, delete-orphan"
    )
    external_ids: Mapped[list["TrackExternalId"]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )


class TrackArtist(Base):
    """Full artist credit of a track, in credit order ("A feat. B")."""

    __tablename__ = "track_artists"
    __table_args__ = (Index("ix_track_artists_artist_id", "artist_id"),)

    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    artist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artists.id", ondelete="RESTRICT"))
    credited_name: Mapped[str] = mapped_column(Text)
    join_phrase: Mapped[str] = mapped_column(Text, server_default="")

    artist: Mapped[Artist] = relationship()


# --- Provider identifiers --------------------------------------------------------------------

EXTERNAL_ID_COMMON_CHECKS = (
    CheckConstraint("confidence > 0 AND confidence <= 1", name="confidence_range"),
)


class TrackExternalId(Base):
    """One canonical track, many provider identifiers (MBID, ISRC, FMA id, Spotify, YouTube)."""

    __tablename__ = "track_external_ids"
    __table_args__ = (
        UniqueConstraint("provider", "external_id"),
        Index("ix_track_external_ids_track_id", "track_id"),
        *EXTERNAL_ID_COMMON_CHECKS,
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    track_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(Text)
    match_method: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    source_id: Mapped[uuid.UUID] = source_fk()
    created_at: Mapped[datetime] = created_at_column()

    track: Mapped[Track] = relationship(back_populates="external_ids")


class ArtistExternalId(Base):
    __tablename__ = "artist_external_ids"
    __table_args__ = (
        UniqueConstraint("provider", "external_id"),
        Index("ix_artist_external_ids_artist_id", "artist_id"),
        *EXTERNAL_ID_COMMON_CHECKS,
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    artist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(Text)
    match_method: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    source_id: Mapped[uuid.UUID] = source_fk()
    created_at: Mapped[datetime] = created_at_column()

    artist: Mapped[Artist] = relationship(back_populates="external_ids")


class AlbumExternalId(Base):
    __tablename__ = "album_external_ids"
    __table_args__ = (
        UniqueConstraint("provider", "external_id"),
        Index("ix_album_external_ids_album_id", "album_id"),
        *EXTERNAL_ID_COMMON_CHECKS,
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    album_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("albums.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(Text)
    match_method: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    source_id: Mapped[uuid.UUID] = source_fk()
    created_at: Mapped[datetime] = created_at_column()

    album: Mapped[Album] = relationship(back_populates="external_ids")


class EntityMatchCandidate(Base):
    """A possible duplicate that the resolution policy refused to link automatically."""

    __tablename__ = "entity_match_candidates"
    __table_args__ = (
        UniqueConstraint("track_id", "candidate_track_id"),
        CheckConstraint("status IN ('pending', 'accepted', 'rejected')", name="status_valid"),
        CheckConstraint("track_id <> candidate_track_id", name="distinct_tracks"),
        Index("ix_entity_match_candidates_status", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    track_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"))
    candidate_track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE")
    )
    confidence: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    source_id: Mapped[uuid.UUID] = source_fk()
    created_at: Mapped[datetime] = created_at_column()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Genres and features ---------------------------------------------------------------------


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, unique=True)
    musicbrainz_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, unique=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("genres.id", ondelete="SET NULL")
    )
    source_id: Mapped[uuid.UUID] = source_fk()
    created_at: Mapped[datetime] = created_at_column()


class TrackGenre(Base):
    """Genre association with its strength: `weight` is the share of the source's genre votes."""

    __tablename__ = "track_genres"
    __table_args__ = (
        CheckConstraint("weight > 0 AND weight <= 1", name="weight_range"),
        Index("ix_track_genres_genre_id", "genre_id"),
    )

    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), primary_key=True
    )
    # Where the genre was attached: the recording itself, its album, or inherited from its artist.
    level: Mapped[str] = mapped_column(String(16), primary_key=True)
    weight: Mapped[float] = mapped_column(Float)
    vote_count: Mapped[int] = mapped_column(Integer, server_default="1")


class ArtistGenre(Base):
    __tablename__ = "artist_genres"
    __table_args__ = (
        CheckConstraint("weight > 0 AND weight <= 1", name="weight_range"),
        Index("ix_artist_genres_genre_id", "genre_id"),
    )

    artist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), primary_key=True
    )
    weight: Mapped[float] = mapped_column(Float)
    vote_count: Mapped[int] = mapped_column(Integer, server_default="1")


UNIT_RANGE_FEATURES = (
    "energy",
    "danceability",
    "valence",
    "acousticness",
    "instrumentalness",
    "loudness",
)


class TrackFeatures(Base):
    """Audio features from a permitted source, versioned.

    Scales are normalized to [0, 1] except tempo (BPM) and onset_rate (onsets per second).
    docs/DATA_SOURCES.md lists how each source's values map onto these columns.
    """

    __tablename__ = "track_features"
    __table_args__ = (
        *(
            CheckConstraint(f"{name} IS NULL OR {name} BETWEEN 0 AND 1", name=f"{name}_unit_range")
            for name in UNIT_RANGE_FEATURES
        ),
        CheckConstraint("tempo IS NULL OR tempo BETWEEN 20 AND 300", name="tempo_range"),
        CheckConstraint("onset_rate IS NULL OR onset_rate >= 0", name="onset_rate_range"),
    )

    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    feature_source: Mapped[str] = mapped_column(String(32), primary_key=True)
    feature_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    tempo: Mapped[float | None] = mapped_column(Float)
    energy: Mapped[float | None] = mapped_column(Float)
    danceability: Mapped[float | None] = mapped_column(Float)
    valence: Mapped[float | None] = mapped_column(Float)
    acousticness: Mapped[float | None] = mapped_column(Float)
    instrumentalness: Mapped[float | None] = mapped_column(Float)
    loudness: Mapped[float | None] = mapped_column(Float)
    onset_rate: Mapped[float | None] = mapped_column(Float)
    source_id: Mapped[uuid.UUID] = source_fk()
    created_at: Mapped[datetime] = created_at_column()
