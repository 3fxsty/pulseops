"""Incidents and the alerts written with them (ADR-061 to ADR-063)."""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pulseops.db.models import Incident, Notification
from pulseops.incidents import OpenIncident

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
