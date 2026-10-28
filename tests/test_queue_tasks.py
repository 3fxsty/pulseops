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

from pulseops.checker.outcome import up
from pulseops.db.models import Check, Monitor
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


@pytest.fixture
def worker(app_engine, monkeypatch):
    """The real worker app, wired to the test database and a fake checker."""
    sessions = async_sessionmaker(app_engine, expire_on_commit=False)
    monkeypatch.setattr(tasks, "get_sessionmaker", lambda: sessions)
    monkeypatch.setattr(tasks, "Checker", FakeChecker)
    return app


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
