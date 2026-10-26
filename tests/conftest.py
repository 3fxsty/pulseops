"""Shared fixtures for tests that need PostgreSQL.

Tests run against the separate `pulseops_test` database (never the development
one), migrated as the schema owner and exercised as the app role, exactly as
in production.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


class DatabaseTestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    test_database_url: SecretStr  # pulseops_app on pulseops_test
    test_migration_database_url: SecretStr  # pulseops_owner on pulseops_test


@pytest.fixture(scope="session")
def db_settings() -> DatabaseTestSettings:
    return DatabaseTestSettings()


@pytest.fixture(scope="session")
def alembic_config(db_settings: DatabaseTestSettings) -> Config:
    config = Config(ALEMBIC_INI)
    config.attributes["database_url"] = (
        db_settings.test_migration_database_url.get_secret_value()
    )
    return config


@pytest.fixture(scope="session")
def migrated_database(alembic_config: Config) -> None:
    """Rebuild the test schema from scratch once per test run."""
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def app_engine(migrated_database, db_settings: DatabaseTestSettings):
    """Engine connected as pulseops_app; leaves the tables empty afterwards."""
    engine = create_async_engine(db_settings.test_database_url.get_secret_value())
    yield engine
    async with engine.begin() as connection:
        # Checks go with their monitor (ON DELETE CASCADE).
        await connection.execute(text("DELETE FROM monitors"))
    await engine.dispose()


@pytest.fixture
async def session(app_engine):
    async with async_sessionmaker(app_engine, expire_on_commit=False)() as session:
        yield session
