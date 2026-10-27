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


async def get_monitor_by_id(session: AsyncSession, monitor_id: int) -> Monitor | None:
    """By internal id: for the worker, never for anything the API exposes."""
    return await session.get(Monitor, monitor_id)


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
    values = {
        field: _require_validated(value) if field == "url" else value
        for field, value in changes.items()
    }
    reschedule = _needs_check_now(monitor, values)
    for field, value in values.items():
        setattr(monitor, field, value)
    if reschedule:
        monitor.next_check_at = func.now()
    await _commit(session)
    return monitor


def _needs_check_now(monitor: Monitor, values: Mapping[str, object]) -> bool:
    """A new URL or interval, or a reactivation, gets checked right away.

    Otherwise going from a 1-day interval to 30 s would still wait for the old
    slot, possibly a day away.
    """
    changed = {f for f, v in values.items() if getattr(monitor, f) != v}
    reactivated = "is_active" in changed and values["is_active"]
    return bool(changed & {"url", "interval_seconds"}) or reactivated


async def delete_monitor(session: AsyncSession, monitor: Monitor) -> None:
    # Its checks go too, via ON DELETE CASCADE in PostgreSQL.
    await session.delete(monitor)
    await session.commit()
