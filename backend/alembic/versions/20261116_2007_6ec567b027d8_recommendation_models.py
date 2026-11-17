"""Recommendation models: model registry, track popularity, and track/artist content embeddings
with HNSW cosine indexes (docs/DATABASE.md, ADR-015).

Revision ID: 6ec567b027d8
Revises: 65ea8b207eac
Create Date: 2026-11-16 20:07:29.534022

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6ec567b027d8"
down_revision: str | Sequence[str] | None = "65ea8b207eac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("model_type", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("training_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "model_type IN ('popularity', 'content')",
            name=op.f("ck_model_versions_model_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'retired')", name=op.f("ck_model_versions_status_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_versions")),
        sa.UniqueConstraint("version", name=op.f("uq_model_versions_version")),
    )
    op.create_index(
        "uq_model_versions_active_model_type",
        "model_versions",
        ["model_type"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "artist_embeddings",
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("artist_id", sa.Uuid(), nullable=False),
        sa.Column("track_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_embeddings_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_artist_embeddings_model_version_id_model_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("model_version_id", "artist_id", name=op.f("pk_artist_embeddings")),
    )
    op.create_index(
        "ix_artist_embeddings_artist_id", "artist_embeddings", ["artist_id"], unique=False
    )
    op.create_index(
        "ix_artist_embeddings_embedding_hnsw",
        "artist_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "track_embeddings",
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("track_id", sa.Uuid(), nullable=False),
        sa.Column("embedding", Vector(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_track_embeddings_model_version_id_model_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["tracks.id"],
            name=op.f("fk_track_embeddings_track_id_tracks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("model_version_id", "track_id", name=op.f("pk_track_embeddings")),
    )
    op.create_index(
        "ix_track_embeddings_embedding_hnsw",
        "track_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_track_embeddings_track_id", "track_embeddings", ["track_id"], unique=False)
    op.create_table(
        "track_popularity",
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("track_id", sa.Uuid(), nullable=False),
        sa.Column("listeners", sa.Integer(), nullable=False),
        sa.Column("plays", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("recent_listeners", sa.Integer(), nullable=False),
        sa.Column("trending_score", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "listeners >= 0 AND plays >= listeners", name=op.f("ck_track_popularity_counts_valid")
        ),
        sa.CheckConstraint("score BETWEEN 0 AND 1", name=op.f("ck_track_popularity_score_range")),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name=op.f("fk_track_popularity_model_version_id_model_versions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["tracks.id"],
            name=op.f("fk_track_popularity_track_id_tracks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("model_version_id", "track_id", name=op.f("pk_track_popularity")),
    )
    op.create_index(
        "ix_track_popularity_score", "track_popularity", ["model_version_id", "score"], unique=False
    )
    op.create_index("ix_track_popularity_track_id", "track_popularity", ["track_id"], unique=False)
    op.create_index(
        "ix_track_popularity_trending_score",
        "track_popularity",
        ["model_version_id", "trending_score"],
        unique=False,
    )


def downgrade() -> None:
    # Dropping a table drops its indexes.
    for table in ("track_popularity", "track_embeddings", "artist_embeddings", "model_versions"):
        op.drop_table(table)
