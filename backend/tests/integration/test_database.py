import pytest
from sqlalchemy import text

from app.core.database import engine
from tests.integration.migration_runner import run_alembic

pytestmark = pytest.mark.integration


def test_migrations_apply_and_roll_back_from_a_clean_database() -> None:
    run_alembic("downgrade", "base")
    run_alembic("upgrade", "head")
    run_alembic("downgrade", "base")
    run_alembic("upgrade", "head")


@pytest.mark.usefixtures("migrated_database")
async def test_pgvector_extension_is_installed() -> None:
    async with engine.connect() as connection:
        extension = await connection.scalar(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )

    assert extension == "vector"
