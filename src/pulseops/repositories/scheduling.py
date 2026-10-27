"""The check schedule: which monitors are due, claimed so no one else takes them."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pulseops.db.models import Monitor, SchedulerHeartbeat

# Most monitors claimed per scheduler tick; the rest wait for the next one.
CLAIM_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class DueCheck:
    monitor_id: int
    # When the check was due (becomes checks.scheduled_at), not "now".
    scheduled_at: datetime
    interval_seconds: int


async def claim_due_monitors(
    session: AsyncSession, *, limit: int = CLAIM_BATCH_SIZE
) -> Sequence[DueCheck]:
    """Claim the active monitors that are due and move them to their next slot.

    Does NOT commit: the caller enqueues the checks first and commits after,
    so a failed enqueue rolls back and the next tick claims the same slots.

    - FOR NO KEY UPDATE SKIP LOCKED: two schedulers never claim the same
      monitor; the second skips the rows the first has locked.
    - Missed slots are skipped, keeping each monitor's rhythm: the next slot
      is the old one plus the fewest whole intervals that land in the future.
    - Times come from the database clock (now() = transaction start).
    """
    due = (
        select(Monitor.id, Monitor.next_check_at)
        .where(Monitor.is_active, Monitor.next_check_at <= func.now())
        .order_by(Monitor.next_check_at)
        .limit(limit)
        # NO KEY UPDATE (not plain UPDATE): ids never change here, so checks
        # being inserted for these monitors (a foreign key share lock) are
        # not blocked while the batch is enqueued.
        .with_for_update(skip_locked=True, key_share=True)
        .cte("due")
    )
    elapsed = func.extract("epoch", func.now() - due.c.next_check_at)
    intervals = func.floor(elapsed / Monitor.interval_seconds) + 1
    next_check_at = due.c.next_check_at + func.make_interval(
        0, 0, 0, 0, 0, 0, Monitor.interval_seconds * intervals
    )
    claim = (
        update(Monitor)
        .where(Monitor.id == due.c.id)
        # Scheduling is not an edit: keep updated_at as it is.
        .values(next_check_at=next_check_at, updated_at=Monitor.updated_at)
        .returning(Monitor.id, due.c.next_check_at, Monitor.interval_seconds)
        .execution_options(synchronize_session=False)
    )
    rows = await session.execute(claim)
    # UPDATE ... RETURNING does not keep the CTE's order: sort, oldest first.
    return sorted(
        (DueCheck(*row) for row in rows),
        key=lambda due_check: due_check.scheduled_at,
    )


async def record_scheduler_success(session: AsyncSession) -> None:
    """Stamp the heartbeat with the database clock. Does NOT commit.

    Called in the tick's own transaction, so it only lands if the tick
    commits: a tick that fails to enqueue leaves the old time in place.
    """
    statement = (
        insert(SchedulerHeartbeat)
        .values(id=1, last_success_at=func.now())
        .on_conflict_do_update(
            index_elements=[SchedulerHeartbeat.id],
            set_={"last_success_at": func.now()},
        )
    )
    await session.execute(statement)


async def get_scheduler_last_success(session: AsyncSession) -> datetime | None:
    """When the scheduler last completed a tick; None if it never has."""
    return await session.scalar(select(SchedulerHeartbeat.last_success_at))
