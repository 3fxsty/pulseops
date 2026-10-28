"""The worker's ArdiQ tasks: thin wrappers around pulseops.scheduling."""

import logging
from collections.abc import Sequence

from pulseops.checker import Checker
from pulseops.config import get_settings
from pulseops.db.session import get_engine, get_sessionmaker
from pulseops.queue.app import CHECKS_LANE, SCHEDULER_LANE, app
from pulseops.repositories.scheduling import DueCheck
from pulseops.scheduling import run_check, schedule_due_checks
from pulseops.timestamps import from_microseconds, to_microseconds

logger = logging.getLogger(__name__)

SCHEDULER_EVERY_SECONDS = 5
# Safety net above the checker's own 10 s deadline.
CHECK_TASK_TIMEOUT_SECONDS = 30


@app.lifespan
async def resources():
    """One checker (shared TLS setup) and one connection pool per worker."""
    settings = get_settings()
    try:
        async with Checker(
            allow_private_targets=settings.allow_private_targets
        ) as checker:
            yield {"checker": checker, "sessions": get_sessionmaker()}
    finally:
        await get_engine().dispose()


@app.task(
    name="check_monitor",
    priority=CHECKS_LANE,
    # Only infrastructure failures raise (e.g. the database is down); a site
    # that is down is an outcome, not an error. Retrying is safe: the insert
    # is idempotent.
    max_retries=3,
    timeout=CHECK_TASK_TIMEOUT_SECONDS,
)
async def check_monitor(monitor_id: int, scheduled_at_us: int) -> None:
    # Only ids travel through the queue, never the URL. msgpack cannot carry
    # datetimes, hence microseconds (exact, so a re-delivery hits the same key).
    await run_check(
        app.state.sessions,
        app.state.checker,
        monitor_id=monitor_id,
        scheduled_at=from_microseconds(scheduled_at_us),
    )


async def enqueue_checks(due: Sequence[DueCheck]) -> None:
    """One round trip to Valkey for the whole batch."""
    await app.enqueue_many(
        check_monitor.options(
            # Fixed id: the same slot enqueued twice is one task.
            task_id=f"check:{d.monitor_id}:{to_microseconds(d.scheduled_at)}",
            # Not started before the next slot: drop it, the next one covers.
            expire_ms=d.interval_seconds * 1000,
        ).prepare(d.monitor_id, to_microseconds(d.scheduled_at))
        for d in due
    )


@app.cron(
    every=SCHEDULER_EVERY_SECONDS,
    coalesce=True,
    name="schedule_due_checks",
    priority=SCHEDULER_LANE,
    max_retries=0,
)
async def schedule_checks() -> int:
    """Every 5 s: claim the due monitors and enqueue their checks."""
    try:
        return await schedule_due_checks(app.state.sessions, enqueue_checks)
    except Exception as error:
        # The next tick retries in 5 s with the same slots (the claim rolled
        # back). Raising would add a dead letter every 5 s while the database
        # or Valkey is down.
        logger.error("scheduling failed, retrying next tick: %r", error)
        return 0
