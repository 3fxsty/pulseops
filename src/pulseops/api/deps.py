import secrets
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from pulseops.api.errors import unauthorized
from pulseops.config import Settings, get_settings
from pulseops.db.session import get_sessionmaker

# auto_error=False so a missing key goes through our own 401 Problem response.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One database session per request."""
    async with get_sessionmaker()() as session:
        yield session


async def require_api_key(
    request: Request, provided: Annotated[str | None, Security(api_key_header)]
) -> None:
    expected = request.app.state.api_settings.api_key.get_secret_value()
    # Constant-time comparison, on bytes so non-ASCII input cannot raise.
    if provided is None or not secrets.compare_digest(
        provided.encode(), expected.encode()
    ):
        raise unauthorized()


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
