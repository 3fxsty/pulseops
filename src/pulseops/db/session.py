from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from pulseops.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Engine for the app role, created on first use rather than at import."""
    return create_async_engine(
        get_settings().database_url.get_secret_value(),
        pool_pre_ping=True,
        # Keep query parameters out of error messages and logs: they can hold
        # monitor URLs (which may carry tokens), and the queue logs and keeps
        # the error of every failed task.
        hide_parameters=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)
