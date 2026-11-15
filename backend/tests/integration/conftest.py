import pytest

from tests.integration.migration_runner import run_alembic


@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Bring the test database schema up to the latest migration."""
    run_alembic("upgrade", "head")
