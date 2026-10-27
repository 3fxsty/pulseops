from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pulseops.db.models import Monitor
from pulseops.security.validation import ValidatedUrl

URL_UNIQUE_CONSTRAINT = "uq_monitors_url"
UPDATABLE_FIELDS = frozenset({"name", "url", "interval_seconds", "is_active"})


class MonitorUrlConflictError(Exception):
    """Another monitor already uses this URL."""


def _require_validated(url: object) -> str:
    # Only URLs that went through normalization and the SSRF check are stored.
    if not isinstance(url, ValidatedUrl):
        raise TypeError("url must be a ValidatedUrl")
    return url.value


async def _commit(session: AsyncSession) -> None:
    """Commit, turning the URL uniqueness violation into a domain error.

    Relying on the constraint (not a SELECT first) leaves no race window.
    """
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        constraint = getattr(error.orig.__cause__, "constraint_name", None)
        if constraint == URL_UNIQUE_CONSTRAINT:
            raise MonitorUrlConflictError from None
        raise


async def create_monitor(
    session: AsyncSession,
    *,
    name: str,
    url: ValidatedUrl,
    interval_seconds: int,
    is_active: bool,
) -> Monitor:
    monitor = Monitor(
        name=name,
        url=_require_validated(url),
        interval_seconds=interval_seconds,
        is_active=is_active,
    )
    session.add(monitor)
    await _commit(session)
    return monitor


async def get_monitor(session: AsyncSession, public_id: UUID) -> Monitor | None:
    return await session.scalar(select(Monitor).where(Monitor.public_id == public_id))


async def list_monitors(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    is_active: bool | None = None,
) -> tuple[Sequence[Monitor], int]:
    """One page of monitors in creation order, plus the total count."""
    items = select(Monitor).order_by(Monitor.id).limit(limit).offset(offset)
    total = select(func.count()).select_from(Monitor)
    if is_active is not None:
        items = items.where(Monitor.is_active == is_active)
        total = total.where(Monitor.is_active == is_active)
    return (await session.scalars(items)).all(), await session.scalar(total)


async def update_monitor(
    session: AsyncSession, monitor: Monitor, changes: Mapping[str, object]
) -> Monitor:
    unknown = changes.keys() - UPDATABLE_FIELDS
    if unknown:
        raise ValueError(f"Not updatable: {sorted(unknown)}")
    for field, value in changes.items():
        setattr(monitor, field, _require_validated(value) if field == "url" else value)
    await _commit(session)
    return monitor


async def delete_monitor(session: AsyncSession, monitor: Monitor) -> None:
    # Its checks go too, via ON DELETE CASCADE in PostgreSQL.
    await session.delete(monitor)
    await session.commit()
