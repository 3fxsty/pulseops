import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from pulseops.config import MigrationSettings
from pulseops.db import models  # noqa: F401  (registers the tables on Base.metadata)
from pulseops.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    """URL of the schema owner role.

    Tests pass their own URL through `config.attributes`; otherwise it comes
    from MIGRATION_DATABASE_URL. It is never stored in alembic.ini.
    """
    url = config.attributes.get("database_url")
    if url is None:
        url = MigrationSettings().migration_database_url.get_secret_value()
    return url


def run_migrations_offline() -> None:
    """Emit the SQL to stdout instead of running it (`alembic upgrade --sql`)."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(get_url(), poolclass=pool.NullPool)

    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
