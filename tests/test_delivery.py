"""Delivering the outbox of alerts (ADR-063): order, retries, giving up."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from pulseops.alerts import DeliveryError
from pulseops.alerts.telegram import SEND_DEADLINE_SECONDS
from pulseops.db.models import Incident, Monitor, Notification
from pulseops.delivery import MAX_ATTEMPTS, deliver_due_alerts, retry_delay
from pulseops.repositories.notifications import LEASE, claim_next_alert

pytestmark = pytest.mark.anyio

SECRET_URL = "https://example.com/status?token=s3cr3t-t0ken"
STARTED = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
TEMPORARY = DeliveryError("connection_error")
PERMANENT = DeliveryError(
    "http_error", status_code=401, problem="the bot token is not valid"
)


class FakeNotifier:
    """Answers each send as scripted: None delivers, an error fails."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.attempts: list[str] = []
        self.delivered: list[str] = []

    async def send(self, text: str) -> None:
        self.attempts.append(text)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise outcome
        self.delivered.append(text)


@pytest.fixture
def sessions(app_engine):
    return async_sessionmaker(app_engine, expire_on_commit=False)


async def make_incident(session, *, kinds=("opened",)) -> int:
    """An incident with its pending alerts; resolved if a "resolved" one is asked."""
    monitor = Monitor(name="Example", url=SECRET_URL, interval_seconds=60)
    session.add(monitor)
    await session.flush()
    resolved = "resolved" in kinds
    incident = Incident(
        monitor_id=monitor.id,
        started_at=STARTED,
        resolved_at=STARTED + timedelta(minutes=5) if resolved else None,
        resolution="recovered" if resolved else None,
        error_kind="http_error",
        status_code=503,
    )
    session.add(incident)
    await session.flush()
    session.add_all(Notification(incident_id=incident.id, kind=k) for k in kinds)
    await session.commit()
    return incident.id


async def resolve(sessions, incident_id: int, resolution="recovered") -> None:
    """The incident ends now, with its "resolved" alert if the site recovered."""
    async with sessions() as session:
        await session.execute(
            update(Incident)
            .where(Incident.id == incident_id)
            .values(resolved_at=func.now(), resolution=resolution)
        )
        if resolution == "recovered":
            session.add(Notification(incident_id=incident_id, kind="resolved"))
        await session.commit()


def first_lines(texts: list[str]) -> list[str]:
    return [t.splitlines()[0] for t in texts]


async def alerts_of(sessions, incident_id: int) -> dict[str, Notification]:
    async with sessions() as session:
        query = select(Notification).where(Notification.incident_id == incident_id)
        return {n.kind: n for n in await session.scalars(query)}


async def set_alerts(sessions, incident_id: int, **values) -> None:
    async with sessions() as session:
        await session.execute(
            update(Notification)
            .where(Notification.incident_id == incident_id)
            .values(**values)
        )
        await session.commit()


async def seconds_until_next_attempt(sessions, incident_id: int, kind: str) -> float:
    async with sessions() as session:
        return await session.scalar(
            select(
                func.extract("epoch", Notification.next_attempt_at - func.now())
            ).where(Notification.incident_id == incident_id, Notification.kind == kind)
        )


# --- sending ---


async def test_a_due_alert_is_sent_and_marked_sent(session, sessions):
    incident = await make_incident(session)
    notifier = FakeNotifier()

    assert await deliver_due_alerts(sessions, notifier) == 1

    [text_sent] = notifier.delivered
    assert text_sent.startswith("🔴 DOWN: Example\n")
    opened = (await alerts_of(sessions, incident))["opened"]
    assert (opened.status, opened.attempts) == ("sent", 1)
    assert opened.finished_at is not None


async def test_the_url_never_reaches_the_alert_or_the_logs(session, sessions, caplog):
    caplog.set_level(logging.DEBUG)
    await make_incident(session, kinds=("opened", "resolved"))
    notifier = FakeNotifier(PERMANENT)

    await deliver_due_alerts(sessions, notifier)

    assert notifier.attempts  # something was sent and something failed
    assert all("s3cr3t-t0ken" not in t for t in notifier.attempts)
    assert "s3cr3t-t0ken" not in caplog.text
    assert "example.com" not in caplog.text


# --- order within an incident (requested by the project owner) ---


async def test_down_then_recovered_in_order(session, sessions):
    incident = await make_incident(session)
    notifier = FakeNotifier()
    await deliver_due_alerts(sessions, notifier)

    await resolve(sessions, incident)
    await deliver_due_alerts(sessions, notifier)

    assert first_lines(notifier.delivered) == [
        "🔴 DOWN: Example",
        "✅ RECOVERED: Example",
    ]


async def test_recovered_waits_while_down_is_pending(session, sessions):
    # Telegram fails on the "DOWN", and the site recovers before its retry.
    # "RECOVERED" waits for it; the late "DOWN" is then skipped. The end of an
    # incident is never announced before its start.
    incident = await make_incident(session)
    notifier = FakeNotifier(TEMPORARY)
    await deliver_due_alerts(sessions, notifier)
    await resolve(sessions, incident)

    assert await deliver_due_alerts(sessions, notifier) == 0
    assert (await alerts_of(sessions, incident))["resolved"].attempts == 0

    await set_alerts(sessions, incident, next_attempt_at=func.now())
    assert await deliver_due_alerts(sessions, notifier) == 1

    alerts = await alerts_of(sessions, incident)
    assert (alerts["opened"].status, alerts["resolved"].status) == ("skipped", "sent")
    assert first_lines(notifier.delivered) == ["✅ RECOVERED: Example"]


async def test_recovered_goes_once_down_has_failed_for_good(session, sessions):
    incident = await make_incident(session)
    notifier = FakeNotifier(PERMANENT)
    await deliver_due_alerts(sessions, notifier)
    await resolve(sessions, incident)

    assert await deliver_due_alerts(sessions, notifier) == 1

    alerts = await alerts_of(sessions, incident)
    assert (alerts["opened"].status, alerts["resolved"].status) == ("failed", "sent")


# --- an alert is dropped when it is no longer useful, not for its age ---

THREE_DAYS_AGO = func.now() - timedelta(days=3)


async def test_an_old_down_is_sent_while_its_incident_is_open(session, sessions):
    # E.g. a site down since before the worker stopped: no other "DOWN" will
    # ever be written for it, and this one is still true.
    incident = await make_incident(session)
    await set_alerts(sessions, incident, created_at=THREE_DAYS_AGO)
    notifier = FakeNotifier()

    assert await deliver_due_alerts(sessions, notifier) == 1
    assert "Since: 2026-11-03 12:00:00 UTC" in notifier.delivered[0]


async def test_an_old_down_is_skipped_once_its_incident_is_over(session, sessions):
    # Its "RECOVERED" carries the start and the duration.
    incident = await make_incident(session, kinds=("opened", "resolved"))
    await set_alerts(sessions, incident, created_at=THREE_DAYS_AGO)
    notifier = FakeNotifier()

    assert await deliver_due_alerts(sessions, notifier) == 1

    alerts = await alerts_of(sessions, incident)
    assert (alerts["opened"].status, alerts["resolved"].status) == ("skipped", "sent")
    assert first_lines(notifier.attempts) == ["✅ RECOVERED: Example"]


async def test_an_old_recovered_is_always_sent(session, sessions):
    # Never leave anyone believing a site is still down.
    incident = await make_incident(session, kinds=("resolved",))
    await set_alerts(sessions, incident, created_at=THREE_DAYS_AGO)
    notifier = FakeNotifier()

    assert await deliver_due_alerts(sessions, notifier) == 1
    assert first_lines(notifier.delivered) == ["✅ RECOVERED: Example"]


async def test_a_down_of_a_paused_incident_is_skipped(session, sessions):
    # Closed by a pause: no "RECOVERED" exists, and the person paused it.
    incident = await make_incident(session)
    await resolve(sessions, incident, resolution="paused")
    notifier = FakeNotifier()

    assert await deliver_due_alerts(sessions, notifier) == 0
    assert notifier.attempts == []
    assert (await alerts_of(sessions, incident))["opened"].status == "skipped"


# --- retries ---


@pytest.mark.parametrize(
    ("attempts", "retry_after", "seconds"),
    [
        (1, None, 10),
        (2, None, 20),
        (3, None, 40),
        (9, None, 2560),
        (10, None, 3600),  # capped at an hour
        (19, None, 3600),
        (1, 30.0, 30),  # a 429 says how long
    ],
)
def test_waits_grow_up_to_an_hour(attempts, retry_after, seconds):
    assert retry_delay(attempts, retry_after) == timedelta(seconds=seconds)


async def test_a_temporary_failure_is_tried_again_later(session, sessions, caplog):
    incident = await make_incident(session)

    await deliver_due_alerts(sessions, FakeNotifier(TEMPORARY))

    opened = (await alerts_of(sessions, incident))["opened"]
    assert (opened.status, opened.attempts) == ("pending", 1)
    assert 8 < await seconds_until_next_attempt(sessions, incident, "opened") <= 10
    assert "retrying in 10s" in caplog.text


async def test_a_rate_limit_waits_for_retry_after(session, sessions):
    incident = await make_incident(session)
    limited = DeliveryError("rate_limited", status_code=429, retry_after=30)

    await deliver_due_alerts(sessions, FakeNotifier(limited))

    assert 28 < await seconds_until_next_attempt(sessions, incident, "opened") <= 30


# --- giving up ---


async def test_a_permanent_failure_fails_at_once_and_says_why(
    session, sessions, caplog
):
    incident = await make_incident(session)

    await deliver_due_alerts(sessions, FakeNotifier(PERMANENT))

    opened = (await alerts_of(sessions, incident))["opened"]
    assert (opened.status, opened.attempts) == ("failed", 1)
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "failed for good" in record.getMessage()
    assert "the bot token is not valid" in record.getMessage()


async def test_it_gives_up_after_20_attempts(session, sessions, caplog):
    incident = await make_incident(session)
    await set_alerts(sessions, incident, attempts=MAX_ATTEMPTS - 1)

    await deliver_due_alerts(sessions, FakeNotifier(TEMPORARY))

    opened = (await alerts_of(sessions, incident))["opened"]
    assert (opened.status, opened.attempts) == ("failed", MAX_ATTEMPTS)
    assert "gave up after 20 attempts" in caplog.text


async def test_retries_stop_24_hours_after_the_first_attempt(session, sessions, caplog):
    incident = await make_incident(session)
    await set_alerts(
        sessions,
        incident,
        attempts=3,
        first_attempt_at=func.now() - timedelta(hours=24, seconds=1),
    )
    notifier = FakeNotifier()

    await deliver_due_alerts(sessions, notifier)

    assert notifier.attempts == []
    assert (await alerts_of(sessions, incident))["opened"].status == "failed"
    assert "retried for more than 24 h" in caplog.text


async def test_an_old_alert_still_gets_its_retries(session, sessions):
    # Written 3 days ago (the worker was down) and Telegram fails on its first
    # attempt: the 24 h count from that attempt, so it is tried again.
    incident = await make_incident(session)
    await set_alerts(sessions, incident, created_at=THREE_DAYS_AGO)

    await deliver_due_alerts(sessions, FakeNotifier(TEMPORARY))

    opened = (await alerts_of(sessions, incident))["opened"]
    assert (opened.status, opened.attempts) == ("pending", 1)
    assert opened.first_attempt_at is not None


async def test_no_retry_is_scheduled_past_the_window(session, sessions, caplog):
    # A 429 asking to wait past the 24 h: give up now, not hours later.
    incident = await make_incident(session)
    await set_alerts(
        sessions,
        incident,
        attempts=2,
        first_attempt_at=func.now() - timedelta(hours=23),
    )
    limited = DeliveryError("rate_limited", status_code=429, retry_after=7200)

    await deliver_due_alerts(sessions, FakeNotifier(limited))

    assert (await alerts_of(sessions, incident))["opened"].status == "failed"
    assert "gave up after 3 attempts" in caplog.text


async def test_an_alert_claimed_over_and_over_gives_up(session, sessions):
    # Every claim counts as an attempt, so a worker that dies mid-send again
    # and again cannot keep an alert alive for ever.
    incident = await make_incident(session)
    await set_alerts(sessions, incident, attempts=MAX_ATTEMPTS)
    notifier = FakeNotifier()

    await deliver_due_alerts(sessions, notifier)

    assert notifier.attempts == []
    assert (await alerts_of(sessions, incident))["opened"].status == "failed"


# --- alerts off (ADR-066) ---


async def test_without_a_bot_pending_alerts_are_skipped(session, sessions):
    incident = await make_incident(session, kinds=("opened", "resolved"))
    # Not due yet: skipped as well, so nothing piles up for later.
    await set_alerts(sessions, incident, next_attempt_at=func.now() + LEASE)

    assert await deliver_due_alerts(sessions, None) == 0

    alerts = await alerts_of(sessions, incident)
    assert {k: a.status for k, a in alerts.items()} == {
        "opened": "skipped",
        "resolved": "skipped",
    }
    assert all(a.finished_at is not None for a in alerts.values())


# --- claiming ---


async def test_two_deliveries_never_claim_the_same_alert(session, sessions):
    await make_incident(session)

    async def claim():
        async with sessions() as s:
            return await claim_next_alert(s)

    claims = await asyncio.gather(claim(), claim())

    assert sorted(c is None for c in claims) == [False, True]
    # Leased: not claimable again until the lease is over.
    assert await claim() is None


async def test_a_claimed_alert_comes_back_after_its_lease(session, sessions):
    # The worker died mid-send: once the lease is over, it is claimed again.
    incident = await make_incident(session)
    async with sessions() as s:
        first = await claim_next_alert(s)
    await set_alerts(sessions, incident, next_attempt_at=func.now())

    async with sessions() as s:
        again = await claim_next_alert(s)

    assert (first.attempts, again.attempts) == (1, 2)


def test_the_lease_outlasts_a_send_with_room_to_spare():
    # Requested by the project owner: a slow send must never let another
    # delivery claim the same alert while it is still being sent.
    assert LEASE.total_seconds() >= 3 * SEND_DEADLINE_SECONDS


async def test_a_run_stops_claiming_when_its_time_is_up(session, sessions):
    await make_incident(session)
    notifier = FakeNotifier()

    assert await deliver_due_alerts(sessions, notifier, budget_seconds=0) == 0
    assert notifier.attempts == []


async def test_alerts_of_deleted_monitors_disappear(session, sessions):
    incident = await make_incident(session)
    async with sessions() as s:
        await s.execute(text("DELETE FROM monitors"))
        await s.commit()

    assert await deliver_due_alerts(sessions, FakeNotifier()) == 0
    assert await alerts_of(sessions, incident) == {}
