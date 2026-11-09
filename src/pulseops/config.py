"""Application configuration, read from environment variables and `.env`.

Values that carry credentials are `SecretStr`, so they never show up in logs,
tracebacks or reprs. Call `.get_secret_value()` only where the raw value is
actually needed. `hide_input_in_errors` keeps them out of validation errors
too (e.g. an API key that is one character too short).
"""

import re
from functools import lru_cache
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_KEY_MIN_LENGTH = 32
# A bot token as BotFather issues it: the bot's id, a colon, then the secret.
TELEGRAM_TOKEN_PATTERN = re.compile(r"\d+:[A-Za-z0-9_-]{30,}")
# A user or group id (groups are negative), or a public @channel name.
TELEGRAM_CHAT_ID_PATTERN = re.compile(r"-?\d+|@[A-Za-z][A-Za-z0-9_]{4,31}")


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
    # Serves /docs, /redoc and /openapi.json. Off unless asked for: the API map
    # helps attackers, so a forgotten variable must not expose it (ADR-027).
    docs_enabled: bool = False


class BrokerSettings(BaseSettings):
    """Settings only the worker needs, kept apart so the API never sees them.

    The API does not use the queue (the scheduler reads monitors from the
    database), so it never gets the Valkey password.
    """

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    broker_url: SecretStr


class AlertSettings(BaseSettings):
    """Telegram alerts (ADR-066). The worker only: the API never gets the token.

    Optional: without them, incidents are still recorded but no alert is sent.
    Both or neither, so a half-configured bot stops the worker at start-up
    instead of silently sending nothing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
        # TELEGRAM_BOT_TOKEN= (empty, as in .env.example) means "not set".
        env_ignore_empty=True,
    )

    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    @field_validator("telegram_bot_token")
    @classmethod
    def _token_looks_like_one(cls, token: SecretStr | None) -> SecretStr | None:
        if token is not None and not TELEGRAM_TOKEN_PATTERN.fullmatch(
            token.get_secret_value()
        ):
            # Never echo the value: it may be a real token with a typo.
            raise ValueError("must look like <digits>:<at least 30 characters>")
        return token

    @field_validator("telegram_chat_id")
    @classmethod
    def _chat_id_looks_like_one(cls, chat_id: str | None) -> str | None:
        if chat_id is not None and not TELEGRAM_CHAT_ID_PATTERN.fullmatch(chat_id):
            raise ValueError("must be a number or an @channel name")
        return chat_id

    @model_validator(mode="after")
    def _both_or_neither(self) -> Self:
        if (self.telegram_bot_token is None) != (self.telegram_chat_id is None):
            raise ValueError(
                "set both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, or neither"
            )
        return self

    @property
    def enabled(self) -> bool:
        return self.telegram_bot_token is not None


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
