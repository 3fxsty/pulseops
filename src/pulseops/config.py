"""Application configuration, read from environment variables and `.env`.

Values that carry credentials are `SecretStr`, so they never show up in logs,
tracebacks or reprs. Call `.get_secret_value()` only where the raw value is
actually needed. `hide_input_in_errors` keeps them out of validation errors
too (e.g. an API key that is one character too short).
"""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

API_KEY_MIN_LENGTH = 32


class Settings(BaseSettings):
    """Runtime settings shared by the API and the worker."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    # Connects as the least-privileged role (pulseops_app): rows only, no DDL.
    database_url: SecretStr
    # SSRF protection: private, loopback and reserved targets are blocked
    # unless explicitly allowed (e.g. a self-hosted install on a private net).
    allow_private_targets: bool = False


class ApiSettings(BaseSettings):
    """Settings only the API needs, kept apart so the worker never sees them."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    api_key: SecretStr = Field(min_length=API_KEY_MIN_LENGTH)
    # Serves /docs, /redoc and /openapi.json.
    docs_enabled: bool = True


class BrokerSettings(BaseSettings):
    """Settings only the worker needs, kept apart so the API never sees them.

    The API does not use the queue (the scheduler reads monitors from the
    database), so it never gets the Valkey password.
    """

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    broker_url: SecretStr


class MigrationSettings(BaseSettings):
    """Settings for Alembic only, kept apart so the app never sees them."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    # Connects as the schema owner (pulseops_owner).
    migration_database_url: SecretStr


@lru_cache
def get_settings() -> Settings:
    return Settings()
