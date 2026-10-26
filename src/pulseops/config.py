"""Application configuration, read from environment variables and `.env`.

Values that carry credentials are `SecretStr`, so they never show up in logs,
tracebacks or reprs. Call `.get_secret_value()` only where the raw value is
actually needed.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the API and the worker."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Connects as the least-privileged role (pulseops_app): rows only, no DDL.
    database_url: SecretStr
    broker_url: SecretStr
    # SSRF protection: private, loopback and reserved targets are blocked
    # unless explicitly allowed (e.g. a self-hosted install on a private net).
    allow_private_targets: bool = False


class MigrationSettings(BaseSettings):
    """Settings for Alembic only, kept apart so the app never sees them."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Connects as the schema owner (pulseops_owner).
    migration_database_url: SecretStr


@lru_cache
def get_settings() -> Settings:
    return Settings()
