"""Pipeline settings and on-disk data layout."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ML_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ML_ROOT.parent


class MlSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    data_dir: Path = ML_ROOT / "data"
    reports_dir: Path = REPO_ROOT / "docs" / "reports"

    # Secret key for pseudonymising ListenBrainz user names (HMAC). Keep it stable between runs so
    # the same user maps to the same key; never commit it.
    listens_pseudonym_key: SecretStr | None = None
    # Number of most recent daily ListenBrainz incremental dumps to ingest.
    listens_days: int = 14
    # How many of the most-listened recordings form the sample catalogue.
    catalogue_size: int = 30_000
    # A recording must be heard by at least this many distinct users to enter the catalogue.
    catalogue_min_listeners: int = 3

    @property
    def raw_dir(self) -> Path:
        """Downloaded source files, exactly as published (provenance)."""
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        """Derived, reproducible intermediate datasets (Parquet)."""
        return self.data_dir / "processed"


@lru_cache
def get_ml_settings() -> MlSettings:
    return MlSettings()
