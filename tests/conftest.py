"""Shared fixtures for tests that need PostgreSQL.

Tests run against the separate `pulseops_test` database (never the development
one), migrated as the schema owner and exercised as the app role, exactly as
in production.
"""

from ipaddress import ip_address
from pathlib import Path

import httpx2
import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pulseops.api.deps import get_session
from pulseops.config import ApiSettings
from pulseops.main import create_app
from pulseops.security import ssrf

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"
TEST_API_KEY = "test-api-key-0123456789abcdefghijklmnop"
# Any public address will do for names a test does not configure.
DEFAULT_PUBLIC_IP = "93.184.215.14"


class DatabaseTestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    test_database_url: SecretStr  # pulseops_app on pulseops_test
    test_migration_database_url: SecretStr  # pulseops_owner on pulseops_test


class BrokerTestSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    test_broker_url: SecretStr  # Valkey logical database 1, not the dev one


@pytest.fixture(scope="session")
def db_settings() -> DatabaseTestSettings:
    return DatabaseTestSettings()


@pytest.fixture(scope="session")
def test_broker_url() -> str:
    return BrokerTestSettings().test_broker_url.get_secret_value()


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
        await connection.execute(text("DELETE FROM scheduler_heartbeat"))
    await engine.dispose()


@pytest.fixture
async def session(app_engine):
    async with async_sessionmaker(app_engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def fake_dns(monkeypatch) -> dict[str, list[str] | None]:
    """Simulated DNS, so tests never depend on the network.

    Map a hostname to a list of IPs, or to None to simulate a failed lookup.
    Names not in the map resolve to a public address.
    """
    records: dict[str, list[str] | None] = {}

    async def resolve(host: str):
        answer = records.get(host, [DEFAULT_PUBLIC_IP])
        return None if answer is None else [ip_address(ip) for ip in answer]

    monkeypatch.setattr(ssrf, "resolve_host", resolve)
    return records


@pytest.fixture
def api_key() -> str:
    return TEST_API_KEY


@pytest.fixture
def app(app_engine):
    app = create_app(ApiSettings(api_key=TEST_API_KEY, docs_enabled=True))
    sessionmaker = async_sessionmaker(app_engine, expire_on_commit=False)

    async def test_session():
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    return app


@pytest.fixture
async def client(app, fake_dns):
    """API client authenticated with the test API key."""
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as client:
        yield client
