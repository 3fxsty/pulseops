"""Incidents and the alerts written with them (ADR-061 to ADR-063)."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Row, Select, delete, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from pulseops.db.models import Incident, Monitor, Notification
from pulseops.incidents import OpenIncident

# The API's `state` filter, from a closed list (never user-built SQL).
STATES = {
    "open": Incident.resolved_at.is_(None),
    "resolved": Incident.resolved_at.is_not(None),
}

# First key of the two-key advisory lock taken per monitor. Any other advisory
# lock in PulseOps must use a different first key, so they never collide.
INCIDENTS_LOCK_SPACE = 1


async def lock_monitor_incidents(session: AsyncSession, monitor_id: int) -> None:
    """Wait until no other transaction is changing this monitor's incidents.

    A transaction-level advisory lock: released on commit or rollback. It
    locks no row, so the scheduler and other monitors never wait for it.
    """
    await session.execute(
        select(func.pg_advisory_xact_lock(INCIDENTS_LOCK_SPACE, monitor_id))
    )


async def latest_incident(session: AsyncSession, monitor_id: int) -> Incident | None:
    """The monitor's newest incident: the open one, or else the last resolved.

    A monitor's incidents never overlap (one opens only after the previous one
    ended), so the newest by start is also the last one to end.
    """
    query = (
        select(Incident)
        .where(Incident.monitor_id == monitor_id)
        .order_by(Incident.started_at.desc())
        .limit(1)
    )
    return await session.scalar(query)


async def get_open_incident(session: AsyncSession, monitor_id: int) -> Incident | None:
    """At most one, by construction (ix_incidents_monitor_id_open)."""
    query = select(Incident).where(
        Incident.monitor_id == monitor_id, Incident.resolved_at.is_(None)
    )
    return await session.scalar(query)


def incidents_statement(
    *,
    limit: int,
    monitor_id: int | None = None,
    state: str | None = None,
    before: tuple[datetime, UUID] | None = None,
) -> Select:
    """Newest first, strictly after `before` in that order (keyset pagination).

    Ordered by (started_at, public_id): two monitors can have incidents that
    start at the same microsecond, and the public id breaks the tie.
    """
    query = select(Incident, Monitor.public_id, Monitor.name).join(
        Monitor, Incident.monitor_id == Monitor.id
    )
    if monitor_id is not None:
        query = query.where(Incident.monitor_id == monitor_id)
    if state is not None:
        query = query.where(STATES[state])
    if before is not None:
        query = query.where(tuple_(Incident.started_at, Incident.public_id) < before)
    return query.order_by(Incident.started_at.desc(), Incident.public_id.desc()).limit(
        limit
    )


async def list_incidents(session: AsyncSession, **filters) -> Sequence[Row]:
    """Rows of (incident, monitor's public id, monitor's name)."""
    return (await session.execute(incidents_statement(**filters))).all()


async def open_incident(
    session: AsyncSession, monitor_id: int, decision: OpenIncident
) -> Incident:
    """A new open incident and its pending "opened" alert, in the caller's
    transaction."""
    incident = Incident(
        monitor_id=monitor_id,
        started_at=decision.started_at,
        error_kind=decision.error_kind,
        status_code=decision.status_code,
    )
    session.add(incident)
    await session.flush()
    session.add(Notification(incident_id=incident.id, kind="opened"))
    await session.flush()
    return incident


async def resolve_incident(
    session: AsyncSession, incident: Incident, *, resolved_at: datetime
) -> None:
    """The site recovered: close the incident and queue the "resolved" alert."""
    incident.resolved_at = resolved_at
    incident.resolution = "recovered"
    session.add(Notification(incident_id=incident.id, kind="resolved"))
    await session.flush()


async def close_open_incident(
    session: AsyncSession, monitor_id: int, resolution: str
) -> bool:
    """End the open incident without a recovery (a pause or a new URL, ADR-062).

    No "resolved" alert: the site did not recover. resolved_at is the time of
    the change, and a streak never reaches back past it (ADR-060). Returns
    whether an incident was open.
    """
    statement = (
        update(Incident)
        .where(Incident.monitor_id == monitor_id, Incident.resolved_at.is_(None))
        # started_at is a slot from the database's own clock, so never in the
        # future; greatest() still guarantees the ck_incidents_resolved_after_
        # started constraint can never make a pause fail.
        .values(
            resolved_at=func.greatest(func.now(), Incident.started_at),
            resolution=resolution,
        )
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(statement)
    return result.rowcount > 0


async def delete_expired_incidents(
    session: AsyncSession, *, retention: timedelta
) -> int:
    """Delete incidents resolved more than `retention` ago, with their alerts.

    One statement: incidents are few (one row per outage). Open incidents are
    never deleted, however old.
    """
    result = await session.execute(
        delete(Incident).where(Incident.resolved_at < func.now() - retention)
    )
    await session.commit()
    return result.rowcount
