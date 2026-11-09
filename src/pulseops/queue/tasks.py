"""The worker's ArdiQ tasks: thin wrappers around pulseops.scheduling,
pulseops.retention and pulseops.delivery."""

import logging
from collections.abc import Sequence
from contextlib import AsyncExitStack

from pulseops.alerts import TelegramNotifier
from pulseops.alerts.telegram import SEND_DEADLINE_SECONDS
from pulseops.checker import Checker
from pulseops.config import AlertSettings, get_settings
from pulseops.db.session import get_engine, get_sessionmaker
from pulseops.delivery import RUN_BUDGET_SECONDS, deliver_due_alerts
from pulseops.queue.app import (
    ALERTS_LANE,
    CHECKS_LANE,
    MAINTENANCE_LANE,
    SCHEDULER_LANE,
    app,
)
from pulseops.repositories.scheduling import DueCheck
from pulseops.retention import (
    MAX_RUN_SECONDS,
    purge_expired_checks,
    purge_expired_incidents,
)
from pulseops.scheduling import run_check, schedule_due_checks
from pulseops.timestamps import from_microseconds, to_microseconds

logger = logging.getLogger(__name__)

SCHEDULER_EVERY_SECONDS = 5
# Safety net above the checker's own 10 s deadline.
CHECK_TASK_TIMEOUT_SECONDS = 30
RETENTION_EVERY_SECONDS = 3600
# Safety net above the cleanup's own 60 s budget, which stops between batches;
# this one would cut a batch short, so it should never be reached.
RETENTION_TASK_TIMEOUT_SECONDS = MAX_RUN_SECONDS + 30
DELIVERY_EVERY_SECONDS = 5
# Safety net above a run's own budget plus the last send's deadline.
DELIVERY_TASK_TIMEOUT_SECONDS = RUN_BUDGET_SECONDS + SEND_DEADLINE_SECONDS + 20


@app.lifespan
async def resources():
    """One checker, one alert channel and one connection pool per worker.

    Invalid alert settings stop the worker here, at start-up (ADR-066).
    """
    settings = get_settings()
    alert_settings = AlertSettings()
    try:
        async with AsyncExitStack() as stack:
            checker = await stack.enter_async_context(
                Checker(allow_private_targets=settings.allow_private_targets)
            )
            notifier = None
            if alert_settings.enabled:
                notifier = await stack.enter_async_context(
                    TelegramNotifier(
                        token=alert_settings.telegram_bot_token,
                        chat_id=alert_settings.telegram_chat_id,
                    )
                )
            else:
                # Incidents are still recorded; their alerts become skipped.
                logger.warning(
                    "alerts are off: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
                    "to send them"
                )
            yield {
                "checker": checker,
                "notifier": notifier,
                "sessions": get_sessionmaker(),
            }
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


@app.cron(
    every=RETENTION_EVERY_SECONDS,
    coalesce=True,
    name="delete_expired_checks",
    # Its own lane (limit 1): a long cleanup never takes the scheduler's slot.
    priority=MAINTENANCE_LANE,
    max_retries=0,
    timeout=RETENTION_TASK_TIMEOUT_SECONDS,
)
async def delete_expired() -> int:
    """Every hour: delete checks older than 30 days, for at most 60 s, then
    incidents resolved more than a year ago (one quick statement)."""
    try:
        checks = await purge_expired_checks(app.state.sessions)
        return checks + await purge_expired_incidents(app.state.sessions)
    except Exception as error:
        # Batches already deleted stay deleted; the next run picks up the rest.
        logger.error("retention failed, retrying next run: %r", error)
        return 0


@app.cron(
    every=DELIVERY_EVERY_SECONDS,
    coalesce=True,
    name="deliver_notifications",
    # Its own lane (limit 1): slow alerts never take the scheduler's slot.
    priority=ALERTS_LANE,
    max_retries=0,
    timeout=DELIVERY_TASK_TIMEOUT_SECONDS,
)
async def deliver_notifications() -> int:
    """Every 5 s: send the pending alerts (ADR-063)."""
    try:
        return await deliver_due_alerts(app.state.sessions, app.state.notifier)
    except Exception as error:
        # The next run picks up where this one stopped. Only the type is
        # logged: an unexpected error from the alert channel might quote the
        # Bot API URL, which holds the token.
        logger.error(
            "alert delivery failed, retrying next run: %s", type(error).__name__
        )
        return 0
