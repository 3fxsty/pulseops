"""The outbox of alerts: claiming, finishing and retrying them (ADR-063)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from pulseops.db.models import Incident, Monitor, Notification

# How long a claimed alert stays out of reach of other deliveries. A send has
# a 10 s deadline, so it always ends well inside its lease; if the worker dies
# mid-send, the alert is claimed again once the lease is over.
LEASE = timedelta(seconds=60)


@dataclass(frozen=True, slots=True)
class ClaimedAlert:
    id: int
    kind: str
    attempts: int  # this one included
    # Since its first attempt, by the database's clock: 0 on the first one.
    retrying_for: timedelta
    incident_id: UUID
    monitor_id: UUID
    monitor_name: str
    started_at: datetime
    resolved_at: datetime | None
    error_kind: str
    status_code: int | None


def next_alert_statement() -> Select:
    """The next pending alert that is due, locked, skipping locked ones.

    A "resolved" alert waits while its incident's "opened" one is still
    pending (requested by the project owner): never the end before the start.
    """
    opened = aliased(Notification)
    opened_still_pending = exists().where(
        opened.incident_id == Notification.incident_id,
        opened.kind == "opened",
        opened.status == "pending",
    )
    return (
        select(
            Notification.id,
            Notification.kind,
            Incident.public_id,
            Monitor.public_id,
            Monitor.name,
            Incident.started_at,
            Incident.resolved_at,
            Incident.error_kind,
            Incident.status_code,
        )
        .join(Incident, Notification.incident_id == Incident.id)
        .join(Monitor, Incident.monitor_id == Monitor.id)
        .where(
            Notification.status == "pending",
            Notification.next_attempt_at <= func.now(),
            or_(Notification.kind != "resolved", ~opened_still_pending),
        )
        .order_by(Notification.next_attempt_at, Notification.id)
        .limit(1)
        .with_for_update(of=Notification, skip_locked=True)
    )


async def claim_next_alert(session: AsyncSession) -> ClaimedAlert | None:
    """Claim one due alert: count the attempt, lease it, commit.

    Committing before the send means no database connection waits on the
    channel (as for checks, ADR-041). The first claim stamps first_attempt_at.
    """
    row = (await session.execute(next_alert_statement())).one_or_none()
    if row is None:
        return None
    alert_id, kind, incident_id, monitor_id, name, *incident = row
    attempts, retrying_for = (
        await session.execute(
            update(Notification)
            .where(Notification.id == alert_id)
            .values(
                attempts=Notification.attempts + 1,
                next_attempt_at=func.now() + LEASE,
                first_attempt_at=func.coalesce(
                    Notification.first_attempt_at, func.now()
                ),
            )
            .returning(
                Notification.attempts, func.now() - Notification.first_attempt_at
            )
        )
    ).one()
    await session.commit()
    return ClaimedAlert(
        alert_id, kind, attempts, retrying_for, incident_id, monitor_id, name, *incident
    )


async def finish_alert(session: AsyncSession, alert_id: int, status: str) -> None:
    """sent, failed or skipped: done for good."""
    await session.execute(
        update(Notification)
        .where(Notification.id == alert_id, Notification.status == "pending")
        .values(status=status, finished_at=func.now())
    )
    await session.commit()


async def retry_alert_later(
    session: AsyncSession, alert_id: int, delay: timedelta
) -> None:
    await session.execute(
        update(Notification)
        .where(Notification.id == alert_id, Notification.status == "pending")
        .values(next_attempt_at=func.now() + delay)
    )
    await session.commit()


async def skip_pending_alerts(session: AsyncSession) -> int:
    """Alerts are off: every pending alert becomes skipped (ADR-066), so
    configuring a bot later does not send a backlog all at once."""
    result = await session.execute(
        update(Notification)
        .where(Notification.status == "pending")
        .values(status="skipped", finished_at=func.now())
    )
    await session.commit()
    return result.rowcount
