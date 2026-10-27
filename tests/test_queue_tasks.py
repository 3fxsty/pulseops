"""The ArdiQ wrappers, run in memory with ardiq.testing.inline (no Valkey).

Tasks still go through msgpack, the lifespan and the registry, as on a worker.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from ardiq.testing import inline
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from pulseops.checker.outcome import up
from pulseops.db.models import Check, Monitor
from pulseops.queue import tasks
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

    assert tasks.from_microseconds(tasks.to_microseconds(moment)) == moment


async def test_check_task_stores_the_outcome(worker, session):
    monitor = await add_monitor(session)
    slot = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)

    async with inline(worker):
        job = await tasks.check_monitor.enqueue(monitor.id, tasks.to_microseconds(slot))
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
