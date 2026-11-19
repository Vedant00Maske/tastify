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

    # --- Music platform integrations (Milestone 5; INTEGRATIONS.md, ADR-018) -----------------
    # 32 random bytes, base64: encrypts provider access and refresh tokens at rest (AES-256-GCM).
    # Without it no account can be connected. Generate: python -c "import os,base64;
    # print(base64.b64encode(os.urandom(32)).decode())"
    integrations_token_key: str | None = None
    # The public address of the web app: OAuth redirect URIs are
    # {app_public_url}/api/v1/integrations/{provider}/callback (through the Next.js proxy).
    app_public_url: str = "http://127.0.0.1:3000"
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Daily YouTube Data API budget (default project quota 10,000 units; reset at midnight
    # Pacific time). TASTIFY stops before an operation would exceed it.
    youtube_daily_quota: int = 10_000

    # Recommendation logs (Milestone 6) are personal data: kept this many days, then pruned
    # (`python -m tastify_ml experiments prune`).
    recommendation_log_retention_days: int = 90

    def redirect_uri(self, provider: str) -> str:
        base = self.app_public_url.rstrip("/")
        return f"{base}{self.api_v1_prefix}/integrations/{provider}/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
