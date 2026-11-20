import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("CORS_ORIGINS", '["https://soniqueo.example"]')

    settings = Settings(_env_file=None)

    assert settings.environment == "staging"
    assert settings.cors_origins == ["https://soniqueo.example"]


def test_unknown_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod-ish")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
