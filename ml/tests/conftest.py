"""Shared fixtures. Like backend/tests/conftest.py, test service URLs are set before any
application module is imported, so the shared engine points at the isolated test database."""

import io
import os
import subprocess
import sys
import tarfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import zstandard

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://tastify:tastify@127.0.0.1:5432/tastify_test"
)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
CATALOGUE_TABLES = (
    "track_features, track_genres, artist_genres, entity_match_candidates, track_external_ids, "
    "track_artists, tracks, album_external_ids, albums, artist_external_ids, artists, genres, "
    "raw_records, ingestion_errors, ingestion_jobs, data_sources, model_versions, users"
)


def write_tar_zst(path: Path, members: dict[str, bytes]) -> Path:
    """Build a small .tar.zst archive with the given members, in order."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    path.write_bytes(zstandard.ZstdCompressor().compress(buffer.getvalue()))
    return path


@pytest.fixture(scope="session")
def migrated_database() -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR, check=True
    )


@pytest.fixture
async def session(migrated_database: None) -> AsyncIterator[object]:
    from sqlalchemy import text

    from app.core.database import SessionFactory

    async with SessionFactory() as db:
        await db.execute(text(f"TRUNCATE {CATALOGUE_TABLES} CASCADE"))
        await db.commit()
        yield db


@pytest.fixture(scope="session", autouse=True)
async def _close_engine() -> AsyncIterator[None]:
    yield
    from app.core.database import engine

    await engine.dispose()
