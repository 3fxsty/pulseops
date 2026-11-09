"""Delivering the alerts written with incidents (ADR-063).

What the worker's deliver_notifications cron runs every 5 s, without the
queue: claim one due alert, send it, record what happened, and repeat.
"""

import logging
import time
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pulseops.alerts import DeliveryError, Notifier
from pulseops.alerts.messages import IncidentSummary, alert_text
from pulseops.repositories.notifications import (
    ClaimedAlert,
    claim_next_alert,
    finish_alert,
    retry_alert_later,
    skip_pending_alerts,
)

logger = logging.getLogger(__name__)

Sessions = async_sessionmaker[AsyncSession]

# Giving up on retries (requested by the project owner): after 20 attempts or
# 24 h since the first one. An alert is never dropped for its age alone: what
# matters is whether it is still useful (see _deliver).
MAX_ATTEMPTS = 20
RETRY_WINDOW = timedelta(hours=24)
# Temporary failures wait 10 s, 20 s, 40 s... up to an hour.
FIRST_RETRY = timedelta(seconds=10)
LONGEST_RETRY = timedelta(hours=1)
# No new alert is claimed after this, so a run ends within its task timeout.
RUN_BUDGET_SECONDS = 30.0


def retry_delay(attempts: int, retry_after: float | None = None) -> timedelta:
    """How long to wait after the given number of failed attempts.

    A 429 says how long itself (retry_after); otherwise the wait doubles.
    """
    if retry_after is not None:
        return timedelta(seconds=retry_after)
    return min(FIRST_RETRY * 2 ** (attempts - 1), LONGEST_RETRY)


async def deliver_due_alerts(
    sessions: Sessions,
    notifier: Notifier | None,
    *,
    budget_seconds: float = RUN_BUDGET_SECONDS,
) -> int:
    """Deliver due alerts one at a time; return how many were sent.

    Each alert is claimed just before it is sent, so every send starts with
    a full lease. Without a notifier (alerts off), pending alerts are skipped.
    """
    if notifier is None:
        async with sessions() as session:
            skipped = await skip_pending_alerts(session)
        if skipped:
            logger.info("alerts are off: %s alert(s) skipped", skipped)
        return 0

    sent = 0
    started = time.monotonic()
    while time.monotonic() - started < budget_seconds:
        async with sessions() as session:
            alert = await claim_next_alert(session)
        if alert is None:
            break
        sent += await _deliver(sessions, notifier, alert)
    return sent


async def _deliver(sessions: Sessions, notifier: Notifier, alert: ClaimedAlert) -> bool:
    if alert.kind == "opened" and alert.resolved_at is not None:
        # The incident is already over: its "RECOVERED" alert carries the start
        # and the duration, so a late "DOWN" would only be noise. An incident
        # closed by a pause or a new URL has no "RECOVERED", and the person
        # made that change themselves.
        await _finish(sessions, alert, "skipped")
        logger.info("%s skipped: the incident is already over", _describe(alert))
        return False
    if alert.attempts > MAX_ATTEMPTS or alert.retrying_for >= RETRY_WINDOW:
        # Claimed again and again without an answer (e.g. a crash mid-send),
        # or a retry that came due past the window (e.g. a long 429 wait).
        await _finish(sessions, alert, "failed")
        logger.error(
            "%s gave up without sending: %s", _describe(alert), _gave_up(alert)
        )
        return False
    try:
        await notifier.send(alert_text(alert.kind, _summary(alert)))
    except DeliveryError as error:
        # DeliveryError never carries the token or a URL: safe to log.
        delay = retry_delay(alert.attempts, error.retry_after)
        if error.permanent:
            await _finish(sessions, alert, "failed")
            logger.error("%s failed for good: %s", _describe(alert), error)
        elif (
            alert.attempts >= MAX_ATTEMPTS or alert.retrying_for + delay >= RETRY_WINDOW
        ):
            # No retry left: the next one would be the 21st, or past 24 h.
            await _finish(sessions, alert, "failed")
            logger.error(
                "%s gave up after %s attempts: %s",
                _describe(alert),
                alert.attempts,
                error,
            )
        else:
            async with sessions() as session:
                await retry_alert_later(session, alert.id, delay)
            logger.warning(
                "%s not sent, retrying in %ss: %s",
                _describe(alert),
                int(delay.total_seconds()),
                error,
            )
        return False
    await _finish(sessions, alert, "sent")
    logger.info("%s sent", _describe(alert))
    return True


async def _finish(sessions: Sessions, alert: ClaimedAlert, status: str) -> None:
    async with sessions() as session:
        await finish_alert(session, alert.id, status)


def _summary(alert: ClaimedAlert) -> IncidentSummary:
    return IncidentSummary(
        monitor_name=alert.monitor_name,
        monitor_id=alert.monitor_id,
        started_at=alert.started_at,
        error_kind=alert.error_kind,
        status_code=alert.status_code,
        resolved_at=alert.resolved_at,
    )


def _describe(alert: ClaimedAlert) -> str:
    # Ids and kind only: never the monitor's URL or name.
    return (
        f"alert {alert.kind} incident={alert.incident_id} "
        f"monitor={alert.monitor_id} attempt={alert.attempts}"
    )


def _gave_up(alert: ClaimedAlert) -> str:
    if alert.attempts > MAX_ATTEMPTS:
        return f"claimed {alert.attempts} times without an answer"
    return "retried for more than 24 h"
