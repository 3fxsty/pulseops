"""What the worker does, without the queue: plan due checks and run one.

ArdiQ only wraps these (pulseops/queue/tasks.py), so this logic is tested
without Valkey and survives a change of queue.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pulseops.checker import CheckOutcome
from pulseops.incidents import LOOKBACK_CHECKS, OpenIncident, ResolveIncident, decide
from pulseops.repositories.checks import list_checks, record_check
from pulseops.repositories.incidents import (
    latest_incident,
    lock_monitor_incidents,
    open_incident,
    resolve_incident,
)
from pulseops.repositories.monitors import get_monitor_by_id, get_monitor_for_check
from pulseops.repositories.scheduling import (
    DueCheck,
    claim_due_monitors,
    record_scheduler_success,
)

logger = logging.getLogger(__name__)

Sessions = async_sessionmaker[AsyncSession]
Enqueue = Callable[[Sequence[DueCheck]], Awaitable[None]]
IncidentEvent = Literal["opened", "resolved"]


class Checker(Protocol):
    async def check(self, url: str) -> CheckOutcome: ...


async def schedule_due_checks(sessions: Sessions, enqueue: Enqueue) -> int:
    """Claim the due monitors, enqueue their checks, stamp the heartbeat, commit.

    Enqueue first, commit after: if enqueueing fails, the claim rolls back
    and the next tick claims the same slots again, so no check is lost. If
    the commit fails instead, the same checks are enqueued twice, which the
    fixed task ids and ON CONFLICT DO NOTHING absorb.
    """
    async with sessions() as session:
        due = await claim_due_monitors(session)
        if due:
            await enqueue(due)  # raises -> leaving the block rolls back
        # Even with nothing due: a quiet PulseOps must not look dead.
        await record_scheduler_success(session)
        await session.commit()
    return len(due)


async def run_check(
    sessions: Sessions, checker: Checker, *, monitor_id: int, scheduled_at: datetime
) -> CheckOutcome | None:
    """Check one monitor and store the outcome. None if there was nothing to do.

    No database connection is held during the check (up to 10 s): one short
    session reads the monitor, another stores the result.
    """
    async with sessions() as session:
        monitor = await get_monitor_by_id(session, monitor_id)
        if monitor is None or not monitor.is_active:
            logger.info("check skipped monitor_id=%s (deleted or paused)", monitor_id)
            return None
        url, public_id = monitor.url, monitor.public_id

    outcome = await checker.check(url)

    async with sessions() as session:
        stored, event = await store_check(
            session, monitor_id=monitor_id, scheduled_at=scheduled_at, outcome=outcome
        )
    # Never log the URL (it may carry tokens) or error_detail (it may echo it).
    logger.info(
        "check monitor=%s up=%s error_kind=%s response_time_ms=%s stored=%s "
        "incident=%s",
        public_id,
        outcome.is_up,
        outcome.error_kind or "-",
        outcome.response_time_ms if outcome.response_time_ms is not None else "-",
        stored,
        event or "-",
    )
    return outcome


async def store_check(
    session: AsyncSession,
    *,
    monitor_id: int,
    scheduled_at: datetime,
    outcome: CheckOutcome,
) -> tuple[bool, IncidentEvent | None]:
    """Store a check and update the monitor's incidents in one transaction.

    Returns whether the check was stored, and the incident it opened or
    resolved, if any (ADR-061):
    1. Checks of one monitor take turns (an advisory lock), so each one is
       evaluated with the previous one already stored.
    2. The monitor is kept from deletion until commit. Already deleted:
       nothing to store.
    3. Insert the check (a re-delivered one is not stored).
    4. Evaluate only a check that was stored, is the newest of its monitor
       and belongs to an active monitor. A late check stays in the history
       but never opens or closes an incident.
    5. One commit: an incident never exists without its alert.
    """
    await lock_monitor_incidents(session, monitor_id)
    monitor = await get_monitor_for_check(session, monitor_id)
    if monitor is None:
        return False, None
    stored = await record_check(
        session, monitor_id=monitor_id, scheduled_at=scheduled_at, outcome=outcome
    )
    event = None
    if stored and monitor.is_active:
        event = await _track_incidents(
            session, monitor_id, monitor.interval_seconds, scheduled_at
        )
    await session.commit()
    return stored, event


async def _track_incidents(
    session: AsyncSession,
    monitor_id: int,
    interval_seconds: int,
    scheduled_at: datetime,
) -> IncidentEvent | None:
    recent = await list_checks(session, monitor_id=monitor_id, limit=LOOKBACK_CHECKS)
    if recent[0].scheduled_at != scheduled_at:
        return None  # a late check: a newer one already decided
    latest = await latest_incident(session, monitor_id)
    incident_open = latest is not None and latest.resolved_at is None
    decision = decide(
        recent,
        interval_seconds=interval_seconds,
        incident_open=incident_open,
        not_before=None if latest is None else latest.resolved_at,
    )
    if isinstance(decision, OpenIncident):
        await open_incident(session, monitor_id, decision)
        return "opened"
    if isinstance(decision, ResolveIncident):
        await resolve_incident(session, latest, resolved_at=decision.resolved_at)
        return "resolved"
    return None
