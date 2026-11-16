"""Catalogue schema: provenance, canonical tracks/artists/albums, provider identifiers, genres,
audio features and unresolved entity matches (docs/DATABASE.md).

Revision ID: 65ea8b207eac
Revises: 3f6c2a9d1b0e
Create Date: 2026-11-16 16:09:25.277879

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "65ea8b207eac"
down_revision: str | Sequence[str] | None = "3f6c2a9d1b0e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Trigram indexes (fuzzy track/artist search) need pg_trgm; autogenerate does not emit it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "data_sources",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("homepage_url", sa.Text(), nullable=False),
        sa.Column("license", sa.Text(), nullable=False),
        sa.Column("license_url", sa.Text(), nullable=False),
        sa.Column("usage_restriction", sa.String(length=32), nullable=False),
        sa.Column("attribution", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "usage_restriction IN ('none', 'non_commercial', 'research_only')",
            name=op.f("ck_data_sources_usage_restriction_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_sources")),
        sa.UniqueConstraint("key", name=op.f("uq_data_sources_key")),
    )
    op.create_table(
        "artists",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("artist_type", sa.String(length=32), nullable=True),
        sa.Column("area", sa.Text(), nullable=True),
        sa.Column("begin_year", sa.SmallInteger(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_artists_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artists")),
    )
    op.create_index("ix_artists_name", "artists", ["name"], unique=False)
    op.create_index(
        "ix_artists_normalized_name_trgm",
        "artists",
        ["normalized_name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"normalized_name": "gin_trgm_ops"},
    )
    op.create_index(op.f("ix_artists_source_id"), "artists", ["source_id"], unique=False)
    op.create_table(
        "genres",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("musicbrainz_id", sa.Uuid(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["genres.id"],
            name=op.f("fk_genres_parent_id_genres"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_genres_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_genres")),
        sa.UniqueConstraint("musicbrainz_id", name=op.f("uq_genres_musicbrainz_id")),
        sa.UniqueConstraint("name", name=op.f("uq_genres_name")),
    )
    op.create_index(op.f("ix_genres_source_id"), "genres", ["source_id"], unique=False)
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="running", nullable=False),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name=op.f("ck_ingestion_jobs_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_ingestion_jobs_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_jobs")),
    )
    op.create_index(
        "ix_ingestion_jobs_source_id_started_at",
        "ingestion_jobs",
        ["source_id", "started_at"],
        unique=False,
    )
    op.create_table(
        "albums",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("album_type", sa.String(length=32), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("release_year", sa.SmallInteger(), nullable=True),
        sa.Column("primary_artist_id", sa.Uuid(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["primary_artist_id"],
            ["artists.id"],
            name=op.f("fk_albums_primary_artist_id_artists"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_albums_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_albums")),
    )
    op.create_index("ix_albums_primary_artist_id", "albums", ["primary_artist_id"], unique=False)
    op.create_index(op.f("ix_albums_source_id"), "albums", ["source_id"], unique=False)
    op.create_table(
        "artist_external_ids",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("artist_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("match_method", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence > 0 AND confidence <= 1",
            name=op.f("ck_track_external_ids_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_external_ids_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_artist_external_ids_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artist_external_ids")),
        sa.UniqueConstraint(
            "provider", "external_id", name=op.f("uq_artist_external_ids_provider")
        ),
    )
    op.create_index(
        "ix_artist_external_ids_artist_id", "artist_external_ids", ["artist_id"], unique=False
    )
    op.create_index(
        op.f("ix_artist_external_ids_source_id"), "artist_external_ids", ["source_id"], unique=False
    )
    op.create_table(
        "artist_genres",
        sa.Column("artist_id", sa.Uuid(), nullable=False),
        sa.Column("genre_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("vote_count", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "weight > 0 AND weight <= 1", name=op.f("ck_artist_genres_weight_range")
        ),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_artist_genres_artist_id_artists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["genre_id"],
            ["genres.id"],
            name=op.f("fk_artist_genres_genre_id_genres"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_artist_genres_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "artist_id", "genre_id", "source_id", name=op.f("pk_artist_genres")
        ),
    )
    op.create_index("ix_artist_genres_genre_id", "artist_genres", ["genre_id"], unique=False)
    op.create_table(
        "ingestion_errors",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("record_ref", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ingestion_jobs.id"],
            name=op.f("fk_ingestion_errors_job_id_ingestion_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_errors")),
    )
    op.create_index(
        "ix_ingestion_errors_job_id_error_code",
        "ingestion_errors",
        ["job_id", "error_code"],
        unique=False,
    )
    op.create_table(
        "raw_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ingestion_jobs.id"],
            name=op.f("fk_raw_records_job_id_ingestion_jobs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_raw_records_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_records")),
        sa.UniqueConstraint(
            "source_id", "entity_type", "external_id", name=op.f("uq_raw_records_source_id")
        ),
    )
    op.create_table(
        "album_external_ids",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("album_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("match_method", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence > 0 AND confidence <= 1",
            name=op.f("ck_track_external_ids_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["album_id"],
            ["albums.id"],
            name=op.f("fk_album_external_ids_album_id_albums"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_album_external_ids_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_album_external_ids")),
        sa.UniqueConstraint("provider", "external_id", name=op.f("uq_album_external_ids_provider")),
    )
    op.create_index(
        "ix_album_external_ids_album_id", "album_external_ids", ["album_id"], unique=False
    )
    op.create_index(
        op.f("ix_album_external_ids_source_id"), "album_external_ids", ["source_id"], unique=False
    )
    op.create_table(
        "tracks",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("normalized_title", sa.Text(), nullable=False),
        sa.Column("matching_key", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("release_year", sa.SmallInteger(), nullable=True),
        sa.Column("isrc", sa.String(length=12), nullable=True),
        sa.Column("artist_id", sa.Uuid(), nullable=False),
        sa.Column("album_id", sa.Uuid(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "isrc IS NULL OR isrc ~ '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$'",
            name=op.f("ck_tracks_isrc_format"),
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms BETWEEN 1000 AND 10800000",
            name=op.f("ck_tracks_duration_plausible"),
        ),
        sa.ForeignKeyConstraint(
            ["album_id"], ["albums.id"], name=op.f("fk_tracks_album_id_albums"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_tracks_artist_id_artists"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_tracks_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tracks")),
    )
    op.create_index("ix_tracks_album_id", "tracks", ["album_id"], unique=False)
    op.create_index("ix_tracks_artist_id", "tracks", ["artist_id"], unique=False)
    op.create_index("ix_tracks_isrc", "tracks", ["isrc"], unique=False)
    op.create_index("ix_tracks_matching_key", "tracks", ["matching_key"], unique=False)
    op.create_index(
        "ix_tracks_normalized_title_trgm",
        "tracks",
        ["normalized_title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"normalized_title": "gin_trgm_ops"},
    )
    op.create_index(op.f("ix_tracks_source_id"), "tracks", ["source_id"], unique=False)
    op.create_table(
        "entity_match_candidates",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("track_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_track_id", sa.Uuid(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name=op.f("ck_entity_match_candidates_status_valid"),
        ),
        sa.CheckConstraint(
            "track_id <> candidate_track_id",
            name=op.f("ck_entity_match_candidates_distinct_tracks"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_track_id"],
            ["tracks.id"],
            name=op.f("fk_entity_match_candidates_candidate_track_id_tracks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_entity_match_candidates_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["tracks.id"],
            name=op.f("fk_entity_match_candidates_track_id_tracks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_match_candidates")),
        sa.UniqueConstraint(
            "track_id", "candidate_track_id", name=op.f("uq_entity_match_candidates_track_id")
        ),
    )
    op.create_index(
        op.f("ix_entity_match_candidates_source_id"),
        "entity_match_candidates",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_entity_match_candidates_status", "entity_match_candidates", ["status"], unique=False
    )
    op.create_table(
        "track_artists",
        sa.Column("track_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("artist_id", sa.Uuid(), nullable=False),
        sa.Column("credited_name", sa.Text(), nullable=False),
        sa.Column("join_phrase", sa.Text(), server_default="", nullable=False),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            name=op.f("fk_track_artists_artist_id_artists"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["tracks.id"],
            name=op.f("fk_track_artists_track_id_tracks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("track_id", "position", name=op.f("pk_track_artists")),
    )
    op.create_index("ix_track_artists_artist_id", "track_artists", ["artist_id"], unique=False)
    op.create_table(
        "track_external_ids",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("track_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("match_method", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence > 0 AND confidence <= 1",
            name=op.f("ck_track_external_ids_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_track_external_ids_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["tracks.id"],
            name=op.f("fk_track_external_ids_track_id_tracks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_track_external_ids")),
        sa.UniqueConstraint("provider", "external_id", name=op.f("uq_track_external_ids_provider")),
    )
    op.create_index(
        op.f("ix_track_external_ids_source_id"), "track_external_ids", ["source_id"], unique=False
    )
    op.create_index(
        "ix_track_external_ids_track_id", "track_external_ids", ["track_id"], unique=False
    )
    op.create_table(
        "track_features",
        sa.Column("track_id", sa.Uuid(), nullable=False),
        sa.Column("feature_source", sa.String(length=32), nullable=False),
        sa.Column("feature_version", sa.String(length=64), nullable=False),
        sa.Column("tempo", sa.Float(), nullable=True),
        sa.Column("energy", sa.Float(), nullable=True),
        sa.Column("danceability", sa.Float(), nullable=True),
        sa.Column("valence", sa.Float(), nullable=True),
        sa.Column("acousticness", sa.Float(), nullable=True),
        sa.Column("instrumentalness", sa.Float(), nullable=True),
        sa.Column("loudness", sa.Float(), nullable=True),
        sa.Column("onset_rate", sa.Float(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "acousticness IS NULL OR acousticness BETWEEN 0 AND 1",
            name=op.f("ck_track_features_acousticness_unit_range"),
        ),
        sa.CheckConstraint(
            "danceability IS NULL OR danceability BETWEEN 0 AND 1",
            name=op.f("ck_track_features_danceability_unit_range"),
        ),
        sa.CheckConstraint(
            "energy IS NULL OR energy BETWEEN 0 AND 1",
            name=op.f("ck_track_features_energy_unit_range"),
        ),
        sa.CheckConstraint(
            "instrumentalness IS NULL OR instrumentalness BETWEEN 0 AND 1",
            name=op.f("ck_track_features_instrumentalness_unit_range"),
        ),
        sa.CheckConstraint(
            "loudness IS NULL OR loudness BETWEEN 0 AND 1",
            name=op.f("ck_track_features_loudness_unit_range"),
        ),
        sa.CheckConstraint(
            "onset_rate IS NULL OR onset_rate >= 0", name=op.f("ck_track_features_onset_rate_range")
        ),
        sa.CheckConstraint(
            "tempo IS NULL OR tempo BETWEEN 20 AND 300", name=op.f("ck_track_features_tempo_range")
        ),
        sa.CheckConstraint(
            "valence IS NULL OR valence BETWEEN 0 AND 1",
            name=op.f("ck_track_features_valence_unit_range"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_track_features_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["tracks.id"],
            name=op.f("fk_track_features_track_id_tracks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "track_id", "feature_source", "feature_version", name=op.f("pk_track_features")
        ),
    )
    op.create_index(
        op.f("ix_track_features_source_id"), "track_features", ["source_id"], unique=False
    )
    op.create_table(
        "track_genres",
        sa.Column("track_id", sa.Uuid(), nullable=False),
        sa.Column("genre_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("vote_count", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("weight > 0 AND weight <= 1", name=op.f("ck_track_genres_weight_range")),
        sa.ForeignKeyConstraint(
            ["genre_id"],
            ["genres.id"],
            name=op.f("fk_track_genres_genre_id_genres"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["data_sources.id"],
            name=op.f("fk_track_genres_source_id_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["track_id"],
            ["tracks.id"],
            name=op.f("fk_track_genres_track_id_tracks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "track_id", "genre_id", "source_id", "level", name=op.f("pk_track_genres")
        ),
    )
    op.create_index("ix_track_genres_genre_id", "track_genres", ["genre_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_track_genres_genre_id", table_name="track_genres")
    op.drop_table("track_genres")
    op.drop_index(op.f("ix_track_features_source_id"), table_name="track_features")
    op.drop_table("track_features")
    op.drop_index("ix_track_external_ids_track_id", table_name="track_external_ids")
    op.drop_index(op.f("ix_track_external_ids_source_id"), table_name="track_external_ids")
    op.drop_table("track_external_ids")
    op.drop_index("ix_track_artists_artist_id", table_name="track_artists")
    op.drop_table("track_artists")
    op.drop_index("ix_entity_match_candidates_status", table_name="entity_match_candidates")
    op.drop_index(
        op.f("ix_entity_match_candidates_source_id"), table_name="entity_match_candidates"
    )
    op.drop_table("entity_match_candidates")
    op.drop_index(op.f("ix_tracks_source_id"), table_name="tracks")
    op.drop_index(
        "ix_tracks_normalized_title_trgm",
        table_name="tracks",
        postgresql_using="gin",
        postgresql_ops={"normalized_title": "gin_trgm_ops"},
    )
    op.drop_index("ix_tracks_matching_key", table_name="tracks")
    op.drop_index("ix_tracks_isrc", table_name="tracks")
    op.drop_index("ix_tracks_artist_id", table_name="tracks")
    op.drop_index("ix_tracks_album_id", table_name="tracks")
    op.drop_table("tracks")
    op.drop_index(op.f("ix_album_external_ids_source_id"), table_name="album_external_ids")
    op.drop_index("ix_album_external_ids_album_id", table_name="album_external_ids")
    op.drop_table("album_external_ids")
    op.drop_table("raw_records")
    op.drop_index("ix_ingestion_errors_job_id_error_code", table_name="ingestion_errors")
    op.drop_table("ingestion_errors")
    op.drop_index("ix_artist_genres_genre_id", table_name="artist_genres")
    op.drop_table("artist_genres")
    op.drop_index(op.f("ix_artist_external_ids_source_id"), table_name="artist_external_ids")
    op.drop_index("ix_artist_external_ids_artist_id", table_name="artist_external_ids")
    op.drop_table("artist_external_ids")
    op.drop_index(op.f("ix_albums_source_id"), table_name="albums")
    op.drop_index("ix_albums_primary_artist_id", table_name="albums")
    op.drop_table("albums")
    op.drop_index("ix_ingestion_jobs_source_id_started_at", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_index(op.f("ix_genres_source_id"), table_name="genres")
    op.drop_table("genres")
    op.drop_index(op.f("ix_artists_source_id"), table_name="artists")
    op.drop_index(
        "ix_artists_normalized_name_trgm",
        table_name="artists",
        postgresql_using="gin",
        postgresql_ops={"normalized_name": "gin_trgm_ops"},
    )
    op.drop_index("ix_artists_name", table_name="artists")
    op.drop_table("artists")
    op.drop_table("data_sources")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
