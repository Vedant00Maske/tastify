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

    app_name: str = "SONIQUEO"
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://soniqueo:soniqueo@127.0.0.1:5432/soniqueo"
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_broker_url: str = "redis://127.0.0.1:6379/1"
    celery_result_backend: str = "redis://127.0.0.1:6379/2"

    # Parsed from a JSON array, e.g. CORS_ORIGINS='["http://localhost:3000"]'. These are also the
    # origins allowed to send state-changing requests (CSRF Origin check).
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # MusicBrainz/ListenBrainz/MetaBrainz require a User-Agent identifying the app and a contact.
    metabrainz_user_agent: str = "SONIQUEO/0.1.0 ( https://github.com/Vedant00Maske/soniqueo )"

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
    def is_deployed(self) -> bool:
        """Staging or production: real users' data, HTTPS, strict settings."""
        return self.environment in ("staging", "production")

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
    # Pacific time). SONIQUEO stops before an operation would exceed it.
    youtube_daily_quota: int = 10_000

    # Recommendation logs (Milestone 6) are personal data: kept this many days, then pruned
    # (`python -m soniqueo_ml experiments prune`).
    recommendation_log_retention_days: int = 90

    # --- Production hardening (Milestone 7; DEPLOYMENT.md, ADR-020) ------------------------
    # Previous INTEGRATIONS_TOKEN_KEY values, still accepted for decryption while
    # `python -m app.cli rotate-token-key` re-encrypts stored tokens with the current key.
    integrations_token_previous_keys: list[str] = []

    # "json": one JSON object per line (production log shipping); "text": human-readable.
    log_format: Literal["text", "json"] = "text"
    # Interactive API docs (/api/v1/docs, /api/v1/openapi.json); off in production unless set.
    api_docs_enabled_override: bool | None = None
    # Requests with a larger body are refused (413) before they reach a route.
    max_request_body_bytes: int = 1_048_576

    # Database connection pool per process, and a server-side cap on any single statement.
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout_seconds: float = 10.0
    db_statement_timeout_ms: int = 15_000

    # Prometheus metrics at /metrics (outside /api/v1, so the public proxy never forwards it).
    # With a token, scrapers must send `Authorization: Bearer <token>`.
    metrics_enabled: bool = True
    metrics_token: str | None = None
    # The Celery worker serves its own metrics on this port.
    worker_metrics_port: int = 9100
    # Written by the backup job; the worker exposes its age as a metric (alert: backups stopped).
    backup_status_file: str | None = None

    # Error tracking (Sentry or a compatible service). Unset: errors are only logged.
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    # Outgoing e-mail (password reset, address verification). Unset SMTP_HOST: no e-mail is
    # sent and those features report that they are unavailable. Local development uses Mailpit.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_security: Literal["starttls", "tls", "none"] = "starttls"
    mail_from: str = "SONIQUEO <no-reply@soniqueo.invalid>"
    # "queue": the Celery worker delivers, with retries (docker-compose.prod.yml). "inline": the
    # API sends over SMTP itself, without retries, for deployments with no worker (Vercel).
    mail_delivery: Literal["queue", "inline"] = "queue"
    password_reset_minutes: int = 60
    email_verification_hours: int = 48

    # Personalized responses (for you, hidden gems) are cached per user and state for this long
    # (spec §4: p95 below 500 ms for cached and precomputed recommendations). 0 disables.
    recommendation_cache_seconds: int = 600
    # After feedback, the worker precomputes the user's home-page mixes into that cache.
    recommendation_precompute: bool = True

    @property
    def api_docs_enabled(self) -> bool:
        if self.api_docs_enabled_override is not None:
            return self.api_docs_enabled_override
        return self.environment != "production"

    @property
    def mail_enabled(self) -> bool:
        return bool(self.smtp_host)

    def redirect_uri(self, provider: str) -> str:
        base = self.app_public_url.rstrip("/")
        return f"{base}{self.api_v1_prefix}/integrations/{provider}/callback"

    def deployment_problems(self) -> list[str]:
        """Settings that are unsafe outside local development. In production the API refuses to
        start while any remain; in staging they are logged as warnings."""
        problems: list[str] = []
        local_hosts = ("localhost", "127.0.0.1", "[::1]", "0.0.0.0")  # noqa: S104 - a check
        for origin in self.cors_origins:
            if not origin.startswith("https://"):
                problems.append(f"CORS_ORIGINS entry {origin!r} is not https")
            if any(host in origin for host in local_hosts):
                problems.append(f"CORS_ORIGINS entry {origin!r} is a local address")
        if not self.app_public_url.startswith("https://"):
            problems.append("APP_PUBLIC_URL is not https")
        if not self.session_cookie_secure:
            problems.append("session cookies are not Secure (SESSION_COOKIE_SECURE_OVERRIDE)")
        if ":soniqueo@" in self.database_url:
            problems.append("DATABASE_URL uses the development password")
        if not self.mail_enabled:
            problems.append("SMTP_HOST is not set: password reset e-mails cannot be sent")
        if self.log_level == "DEBUG":
            problems.append("LOG_LEVEL is DEBUG")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
