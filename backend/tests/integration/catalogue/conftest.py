import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionFactory
from app.domains.catalogue.provenance import ensure_data_source

CATALOGUE_TABLES = (
    "track_features, track_genres, artist_genres, entity_match_candidates, track_external_ids, "
    "track_artists, tracks, album_external_ids, albums, artist_external_ids, artists, genres, "
    "raw_records, ingestion_errors, ingestion_jobs, data_sources"
)


@pytest.fixture
async def session(migrated_database: None) -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as db:
        await db.execute(text(f"TRUNCATE {CATALOGUE_TABLES} CASCADE"))
        await db.commit()
        yield db


async def register_source(db: AsyncSession, key: str) -> uuid.UUID:
    return await ensure_data_source(
        db,
        key=key,
        name=key,
        homepage_url=f"https://{key}.example",
        license="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        usage_restriction="none",
    )
