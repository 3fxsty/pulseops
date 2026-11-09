"""The ArdiQ wrappers, run in memory with ardiq.testing.inline (no Valkey).

Tasks still go through msgpack, the lifespan and the registry, as on a worker.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from ardiq import Ardiq
from ardiq.testing import inline
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from pulseops.alerts.telegram import SEND_DEADLINE_SECONDS
from pulseops.checker.outcome import up
from pulseops.config import AlertSettings
from pulseops.db.models import Check, Incident, Monitor, Notification
from pulseops.delivery import RUN_BUDGET_SECONDS
from pulseops.queue import tasks
from pulseops.timestamps import from_microseconds, to_microseconds
from pulseops.worker import app

pytestmark = pytest.mark.anyio


class FakeChecker:
    def __init__(self, **_):
        self.urls = []

    async def check(self, url):
        self.urls.append(url)
        return up(200, 42)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        pass


# Made up, and unlike a real token, so scanners never mistake it for one.
FAKE_TOKEN = "123456:fake-token-for-tests-only-not-real"


class FakeTelegram:
    """Stands in for TelegramNotifier: records what it would have sent."""

    sent: list[str] = []

    def __init__(self, **_):
        FakeTelegram.sent = []

    async def send(self, text):
        FakeTelegram.sent.append(text)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        pass


def alert_settings(**values) -> AlertSettings:
    return AlertSettings(_env_file=None, **values)


@pytest.fixture
def worker(app_engine, monkeypatch):
    """The real worker app, wired to the test database and a fake checker.

    Alerts are off whatever the developer's .env says, so no test can ever
    reach a real bot.
    """
    sessions = async_sessionmaker(app_engine, expire_on_commit=False)
    monkeypatch.setattr(tasks, "get_sessionmaker", lambda: sessions)
    monkeypatch.setattr(tasks, "Checker", FakeChecker)
    monkeypatch.setattr(tasks, "AlertSettings", lambda: alert_settings())
    monkeypatch.setattr(tasks, "TelegramNotifier", FakeTelegram)
    return app


@pytest.fixture
def worker_with_alerts(worker, monkeypatch):
    configured = alert_settings(
        telegram_bot_token=FAKE_TOKEN, telegram_chat_id="-1001234567890"
    )
    monkeypatch.setattr(tasks, "AlertSettings", lambda: configured)
    return worker


async def add_monitor(session) -> Monitor:
    monitor = Monitor(
        name="Example",
        url=f"https://example.com/{uuid.uuid4()}",
        interval_seconds=60,
        next_check_at=func.now() - timedelta(seconds=1),
    )
    session.add(monitor)
    await session.commit()
    await session.refresh(monitor)
    return monitor


async def stored_slots(session, monitor_id):
    query = select(Check.scheduled_at).where(Check.monitor_id == monitor_id)
    return list(await session.scalars(query))


def test_microseconds_keep_the_exact_time():
    moment = datetime(2026, 10, 27, 22, 38, 14, 931815, tzinfo=UTC)

    assert from_microseconds(to_microseconds(moment)) == moment


async def test_check_task_stores_the_outcome(worker, session):
    monitor = await add_monitor(session)
    slot = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)

    async with inline(worker):
        job = await tasks.check_monitor.enqueue(monitor.id, to_microseconds(slot))
        assert (await job.result()).success

    assert await stored_slots(session, monitor.id) == [slot]


async def test_scheduler_tick_enqueues_and_runs_the_due_checks(worker, session):
    monitor = await add_monitor(session)

    async with inline(worker):
        claimed = await tasks.schedule_checks()

    assert claimed == 1
    assert await stored_slots(session, monitor.id) == [monitor.next_check_at]


async def test_scheduler_tick_survives_a_broken_broker(worker, session, monkeypatch):
    monitor = await add_monitor(session)

    async def broken(due):
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(tasks, "enqueue_checks", broken)

    async with inline(worker):
        assert await tasks.schedule_checks() == 0

    # Nothing was lost: the monitor is still due for the same slot.
    await session.refresh(monitor)
    assert monitor.next_check_at <= await session.scalar(select(func.now()))


async def test_retention_task_deletes_expired_checks(worker, session):
    monitor = await add_monitor(session)
    for days in (31, 1):
        await session.execute(
            insert(Check).values(
                monitor_id=monitor.id,
                scheduled_at=func.now() - timedelta(days=days),
                is_up=True,
                status_code=200,
                response_time_ms=100,
            )
        )
    await session.commit()

    async with inline(worker):
        assert await tasks.delete_expired() == 1

    assert len(await stored_slots(session, monitor.id)) == 1  # the recent one


async def test_scheduler_error_log_never_shows_the_broker_password(
    worker, session, test_broker_url, monkeypatch, caplog, capfd
):
    # A real ArdiQ against the real Valkey with a wrong password: the error
    # it raises is what the scheduler logs. Slow (~10 s): ArdiQ retries the
    # connection before giving up, and has no option to shorten that.
    password = "wrong-password-0123456789"
    real = urlsplit(test_broker_url)
    broken = Ardiq(
        redis_url=f"redis://:{password}@{real.hostname}:{real.port}/1",
        queue_name=f"pulseops_test_{uuid.uuid4()}",
    )

    async def enqueue(due):
        await broken.send("check_monitor", 1, 2)

    monkeypatch.setattr(tasks, "enqueue_checks", enqueue)
    await add_monitor(session)
    caplog.set_level(logging.DEBUG)

    async with inline(worker):
        assert await tasks.schedule_checks() == 0

    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any("scheduling failed" in message for message in errors)
    output = capfd.readouterr()
    assert password not in caplog.text + output.out + output.err


# --- alerts ---


async def add_pending_alert(session) -> int:
    monitor = await add_monitor(session)
    incident = Incident(
        monitor_id=monitor.id,
        started_at=func.now(),
        error_kind="timeout",
    )
    session.add(incident)
    await session.flush()
    session.add(Notification(incident_id=incident.id, kind="opened"))
    await session.commit()
    return incident.id


async def alert_status(session, incident_id) -> str:
    query = select(Notification.status).where(Notification.incident_id == incident_id)
    return await session.scalar(query.execution_options(populate_existing=True))


async def test_delivery_task_sends_due_alerts(worker_with_alerts, session):
    incident = await add_pending_alert(session)

    async with inline(worker_with_alerts):
        assert await tasks.deliver_notifications() == 1

    assert FakeTelegram.sent[0].startswith("🔴 DOWN: Example")
    assert await alert_status(session, incident) == "sent"


async def test_without_a_bot_the_worker_says_so_and_skips_alerts(
    worker, session, caplog
):
    incident = await add_pending_alert(session)

    async with inline(worker):
        assert await tasks.deliver_notifications() == 0

    assert "alerts are off" in caplog.text
    assert await alert_status(session, incident) == "skipped"


async def test_delivery_task_never_logs_the_token(
    worker_with_alerts, monkeypatch, caplog
):
    # A bug in the channel could raise an error quoting the Bot API URL: the
    # task logs its type only.
    async def broken(sessions, notifier):
        raise ValueError(f"bad url https://api.telegram.org/bot{FAKE_TOKEN}/x")

    monkeypatch.setattr(tasks, "deliver_due_alerts", broken)

    async with inline(worker_with_alerts):
        assert await tasks.deliver_notifications() == 0

    assert "ValueError" in caplog.text
    assert FAKE_TOKEN not in caplog.text


def test_delivery_task_timeout_covers_a_whole_run():
    # A run claims until its budget runs out, then finishes one last send.
    assert tasks.DELIVERY_TASK_TIMEOUT_SECONDS > (
        RUN_BUDGET_SECONDS + SEND_DEADLINE_SECONDS
    )
