import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_alembic(*args: str) -> None:
    """Run alembic in a subprocess so its own asyncio.run() never collides with pytest's loop.

    The subprocess inherits DATABASE_URL from tests/conftest.py, so it targets the test database.
    """
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, check=True)
