"""requirements.txt (Docker image, CI) and pyproject.toml (Vercel) must pin the same runtime
dependencies, or the two deployments would run different code."""

import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def _requirements() -> list[str]:
    lines = (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return sorted(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def test_pyproject_pins_match_requirements() -> None:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert sorted(project["dependencies"]) == _requirements()
