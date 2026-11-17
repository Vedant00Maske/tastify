"""Recommendation model registry and the serving data each model publishes (docs/DATABASE.md).

Models are trained offline (ADR-008) by `python -m tastify_ml recommend` (Milestone 2:
popularity, content) and `python -m tastify_ml personalize` (Milestone 3: collaborative, hybrid).
Publishing a version
writes its serving rows, marks it active and removes the rows of the version it replaces, so each
model type has exactly one active version and the vector indexes only ever hold active vectors.
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.catalogue.models import created_at_column, uuid_pk

# Dimensionality of content embeddings. Changing it needs a migration (the column type is fixed).
EMBEDDING_DIMENSIONS = 128

# Dimensionality of collaborative (ALS) track factors, chosen in the Milestone 3 CF benchmark.
CF_DIMENSIONS = 256

MODEL_TYPES = ("popularity", "content", "collaborative", "hybrid")


def _hnsw_cosine_index(name: str) -> Index:
    return Index(
        name,
        "embedding",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def _version_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"), primary_key=True)


class ModelVersion(Base):
    """One trained model: its hyperparameters, training data window and offline metrics."""

    __tablename__ = "model_versions"
    __table_args__ = (
        CheckConstraint(
            "model_type IN ('popularity', 'content', 'collaborative', 'hybrid')",
            name="model_type_valid",
        ),
        CheckConstraint("status IN ('active', 'retired')", name="status_valid"),
        # At most one active version per model type.
        Index(
            "uq_model_versions_active_model_type",
            "model_type",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    model_type: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Data window, row counts and input fingerprints, so a version can be reproduced.
    training_data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Offline evaluation results (docs/reports/model-benchmark.md).
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()


class TrackPopularity(Base):
    """Listening popularity of a track over the model's data window."""

    __tablename__ = "track_popularity"
    __table_args__ = (
        CheckConstraint("score BETWEEN 0 AND 1", name="score_range"),
        CheckConstraint("listeners >= 0 AND plays >= listeners", name="counts_valid"),
        Index("ix_track_popularity_score", "model_version_id", "score"),
        Index("ix_track_popularity_trending_score", "model_version_id", "trending_score"),
        Index("ix_track_popularity_track_id", "track_id"),
    )

    model_version_id: Mapped[uuid.UUID] = _version_fk()
    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    listeners: Mapped[int] = mapped_column(Integer)
    plays: Mapped[int] = mapped_column(Integer)
    # log(1 + listeners) / log(1 + max listeners): comparable across tracks, in [0, 1].
    score: Mapped[float] = mapped_column(Float)
    recent_listeners: Mapped[int] = mapped_column(Integer)
    # Smoothed log ratio of recent to earlier daily listeners. NULL when there is too little data
    # for the trend to be reliable.
    trending_score: Mapped[float | None] = mapped_column(Float)


class TrackEmbedding(Base):
    """L2-normalized content embedding of a track; cosine similarity = 1 - cosine distance."""

    __tablename__ = "track_embeddings"
    __table_args__ = (
        _hnsw_cosine_index("ix_track_embeddings_embedding_hnsw"),
        Index("ix_track_embeddings_track_id", "track_id"),
    )

    model_version_id: Mapped[uuid.UUID] = _version_fk()
    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class ArtistEmbedding(Base):
    """Artist profile: popularity-weighted mean of the artist's track embeddings, L2-normalized."""

    __tablename__ = "artist_embeddings"
    __table_args__ = (
        _hnsw_cosine_index("ix_artist_embeddings_embedding_hnsw"),
        Index("ix_artist_embeddings_artist_id", "artist_id"),
    )

    model_version_id: Mapped[uuid.UUID] = _version_fk()
    artist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    track_count: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class TrackCollaborativeFactors(Base):
    """ALS track factors. A user's factors are folded in at request time (ADR-016); the
    inner product user . track is the collaborative score, searched with an HNSW index on the
    (negative) inner product."""

    __tablename__ = "track_cf_factors"
    __table_args__ = (
        Index(
            "ix_track_cf_factors_factors_hnsw",
            "factors",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"factors": "vector_ip_ops"},
        ),
        Index("ix_track_cf_factors_track_id", "track_id"),
    )

    model_version_id: Mapped[uuid.UUID] = _version_fk()
    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    factors: Mapped[list[float]] = mapped_column(Vector(CF_DIMENSIONS))
    # BM25 inverse document frequency of the track in training (confidence weighting).
    idf: Mapped[float] = mapped_column(Float)


class TrackNeighbour(Base):
    """Item-item collaborative neighbours: tracks co-listened with `track_id`, and how strongly."""

    __tablename__ = "track_neighbours"

    model_version_id: Mapped[uuid.UUID] = _version_fk()
    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    neighbour_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[float] = mapped_column(Float)


class ModelArtifact(Base):
    """Binary or JSON artifacts of a version (ranker trees, ALS Gram matrix). Kept for retired
    versions too, so a previous ranker can be inspected or restored."""

    __tablename__ = "model_artifacts"

    model_version_id: Mapped[uuid.UUID] = _version_fk()
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    media_type: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()


# Tables holding per-version serving rows (cleared for retired versions on publish).
SERVING_TABLES = (
    TrackPopularity,
    TrackEmbedding,
    ArtistEmbedding,
    TrackCollaborativeFactors,
    TrackNeighbour,
)
