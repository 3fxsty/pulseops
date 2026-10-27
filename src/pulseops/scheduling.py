"""What the worker does, without the queue: plan due checks and run one.

ArdiQ only wraps these (pulseops/queue/tasks.py), so this logic is tested
without Valkey and survives a change of queue.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pulseops.checker import CheckOutcome
from pulseops.repositories.checks import record_check
from pulseops.repositories.monitors import get_monitor_by_id
from pulseops.repositories.scheduling import DueCheck, claim_due_monitors

logger = logging.getLogger(__name__)

Sessions = async_sessionmaker[AsyncSession]
Enqueue = Callable[[Sequence[DueCheck]], Awaitable[None]]


class Checker(Protocol):
    async def check(self, url: str) -> CheckOutcome: ...


async def schedule_due_checks(sessions: Sessions, enqueue: Enqueue) -> int:
    """Claim the due monitors, enqueue their checks, then commit.

    Enqueue first, commit after: if enqueueing fails, the claim rolls back
    and the next tick claims the same slots again, so no check is lost. If
    the commit fails instead, the same checks are enqueued twice, which the
    fixed task ids and ON CONFLICT DO NOTHING absorb.
    """
    async with sessions() as session:
        due = await claim_due_monitors(session)
        if due:
            await enqueue(due)  # raises -> leaving the block rolls back
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
        stored = await record_check(
            session, monitor_id=monitor_id, scheduled_at=scheduled_at, outcome=outcome
        )
    # Never log the URL (it may carry tokens) or error_detail (it may echo it).
    logger.info(
        "check monitor=%s up=%s error_kind=%s response_time_ms=%s stored=%s",
        public_id,
        outcome.is_up,
        outcome.error_kind or "-",
        outcome.response_time_ms if outcome.response_time_ms is not None else "-",
        stored,
    )
    return outcome
