from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import Row, Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pulseops.db.models import Monitor
from pulseops.repositories.incidents import close_open_incident, lock_monitor_incidents
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


def monitor_for_check_statement(monitor_id: int) -> Select:
    # FOR KEY SHARE: the lock a foreign key check takes anyway. It stops the
    # monitor from being deleted until commit, but never conflicts with the
    # scheduler's FOR NO KEY UPDATE claim.
    return (
        select(Monitor.is_active, Monitor.interval_seconds)
        .where(Monitor.id == monitor_id)
        .with_for_update(read=True, key_share=True)
    )


async def get_monitor_for_check(session: AsyncSession, monitor_id: int) -> Row | None:
    """is_active and interval_seconds, with the monitor kept from deletion
    until commit. None if it was already deleted."""
    result = await session.execute(monitor_for_check_statement(monitor_id))
    return result.one_or_none()


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
    changed = {f for f, v in values.items() if getattr(monitor, f) != v}
    reschedule = _needs_check_now(changed, values)
    resolution = _ends_open_incident(changed, values)
    if resolution:
        # The same lock as the incident evaluation (ADR-061), so the two never
        # interleave. Both run before the monitor's own changes: a statement
        # flushes pending changes first, and a duplicate URL must surface in
        # _commit (a 409), where the rollback also undoes this.
        await lock_monitor_incidents(session, monitor.id)
        await close_open_incident(session, monitor.id, resolution)
    for field, value in values.items():
        setattr(monitor, field, value)
    if reschedule:
        monitor.next_check_at = func.now()
    await _commit(session)
    return monitor


def _needs_check_now(changed: set[str], values: Mapping[str, object]) -> bool:
    """A new URL or interval, or a reactivation, gets checked right away.

    Otherwise going from a 1-day interval to 30 s would still wait for the old
    slot, possibly a day away.
    """
    reactivated = "is_active" in changed and values["is_active"]
    return bool(changed & {"url", "interval_seconds"}) or reactivated


def _ends_open_incident(changed: set[str], values: Mapping[str, object]) -> str | None:
    """Pausing or a new URL ends the open incident, without a recovery (ADR-062)."""
    if "is_active" in changed and not values["is_active"]:
        return "paused"
    if "url" in changed:
        return "monitor_changed"
    return None


async def delete_monitor(session: AsyncSession, monitor: Monitor) -> None:
    # Its checks go too, via ON DELETE CASCADE in PostgreSQL.
    await session.delete(monitor)
    await session.commit()
