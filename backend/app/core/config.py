"""Application settings, read from environment variables and the repository-root .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repository root. A missing file is ignored, which is the normal
# case inside containers where configuration arrives as real environment variables.
REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TASTIFY"
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://tastify:tastify@127.0.0.1:5432/tastify"
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_broker_url: str = "redis://127.0.0.1:6379/1"
    celery_result_backend: str = "redis://127.0.0.1:6379/2"

    # Parsed from a JSON array, e.g. CORS_ORIGINS='["http://localhost:3000"]'. These are also the
    # origins allowed to send state-changing requests (CSRF Origin check).
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # MusicBrainz/ListenBrainz/MetaBrainz require a User-Agent identifying the app and a contact.
    metabrainz_user_agent: str = "TASTIFY/0.1.0 ( https://github.com/Vedant00Maske/tastify )"

    # Peers whose X-Forwarded-For header is trusted (the Next.js server proxying /api/v1):
    # addresses or networks, e.g. ["172.16.0.0/12"] for a Docker network.
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]

    # Session cookies are Secure (HTTPS only) outside local development and tests, unless set.
    session_cookie_secure_override: bool | None = None

    @property
    def session_cookie_secure(self) -> bool:
        if self.session_cookie_secure_override is not None:
            return self.session_cookie_secure_override
        return self.environment not in ("local", "test")

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset(self.cors_origins)

    # Album artwork from the Cover Art Archive (MusicBrainz release groups). Images remain the
    # copyright of their owners: suitable for the current non-commercial posture (ADR-013).
    cover_art_enabled: bool = True
    cover_art_url: str = "https://coverartarchive.org/release-group/{mbid}/front-500"


@lru_cache
def get_settings() -> Settings:
    return Settings()
