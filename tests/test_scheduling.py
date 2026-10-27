"""The worker's logic, without the queue: planning checks and running one."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from pulseops.checker.outcome import down, up
from pulseops.db.models import Check, Monitor, SchedulerHeartbeat
from pulseops.db.session import get_engine
from pulseops.repositories.scheduling import get_scheduler_last_success
from pulseops.scheduling import run_check, schedule_due_checks

pytestmark = pytest.mark.anyio

SCHEDULED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
SECRET_URL = "https://example.com/status?token=s3cr3t-t0ken"


@pytest.fixture
def sessions(app_engine):
    return async_sessionmaker(app_engine, expire_on_commit=False)


async def add_monitor(session, *, url=None, active=True, due=True) -> Monitor:
    monitor = Monitor(
        name="Example",
        url=url or f"https://example.com/{uuid.uuid4()}",
        interval_seconds=60,
        is_active=active,
        next_check_at=func.now() - timedelta(seconds=1 if due else -60),
    )
    session.add(monitor)
    await session.commit()
    await session.refresh(monitor)
    await session.commit()  # hand the connection back to the pool
    return monitor


class FakeChecker:
    def __init__(self, outcome=None, on_check=None):
        self.outcome = outcome or up(200, 42)
        self.on_check = on_check
        self.urls: list[str] = []

    async def check(self, url):
        self.urls.append(url)
        if self.on_check:
            self.on_check()
        return self.outcome


# --- schedule_due_checks ---


async def last_success(sessions):
    async with sessions() as session:
        return await get_scheduler_last_success(session)


async def nothing_to_enqueue(due):
    raise AssertionError("nothing should be enqueued")


async def test_due_monitors_are_enqueued_and_moved_on(session, sessions):
    monitor = await add_monitor(session)
    enqueued = []

    async def enqueue(due):
        enqueued.extend(due)

    assert await schedule_due_checks(sessions, enqueue) == 1

    assert [(d.monitor_id, d.scheduled_at) for d in enqueued] == [
        (monitor.id, monitor.next_check_at)
    ]
    await session.refresh(monitor)
    assert monitor.next_check_at > enqueued[0].scheduled_at


async def test_nothing_due_enqueues_nothing(session, sessions):
    await add_monitor(session, due=False)

    assert await schedule_due_checks(sessions, nothing_to_enqueue) == 0


async def test_failed_enqueue_loses_no_check(session, sessions):
    # Valkey is down: the claim rolls back and the next tick retries the slot.
    monitor = await add_monitor(session)
    slot = monitor.next_check_at

    async def broken_enqueue(due):
        raise ConnectionError("broker unreachable")

    with pytest.raises(ConnectionError):
        await schedule_due_checks(sessions, broken_enqueue)

    await session.refresh(monitor)
    assert monitor.next_check_at == slot
    retried = []

    async def enqueue(due):
        retried.extend(due)

    await schedule_due_checks(sessions, enqueue)
    assert [d.scheduled_at for d in retried] == [slot]


async def test_an_empty_tick_still_moves_the_heartbeat(sessions):
    # No monitor is due: PulseOps is quiet, not dead.
    assert await last_success(sessions) is None

    await schedule_due_checks(sessions, nothing_to_enqueue)
    first = await last_success(sessions)
    await schedule_due_checks(sessions, nothing_to_enqueue)
    second = await last_success(sessions)

    assert first is not None
    assert second > first


async def test_a_failed_enqueue_does_not_move_the_heartbeat(session, sessions):
    await schedule_due_checks(sessions, nothing_to_enqueue)
    before = await last_success(sessions)
    await add_monitor(session)

    async def broken_enqueue(due):
        raise ConnectionError("broker unreachable")

    with pytest.raises(ConnectionError):
        await schedule_due_checks(sessions, broken_enqueue)

    assert await last_success(sessions) == before


async def test_the_heartbeat_is_a_single_row(session):
    session.add(SchedulerHeartbeat(id=2, last_success_at=func.now()))

    with pytest.raises(IntegrityError, match="ck_scheduler_heartbeat_single_row"):
        await session.commit()


# --- run_check ---


async def test_checks_the_monitor_and_stores_the_outcome(session, sessions):
    monitor = await add_monitor(session)
    checker = FakeChecker(up(204, 87))

    outcome = await run_check(
        sessions, checker, monitor_id=monitor.id, scheduled_at=SCHEDULED_AT
    )

    assert outcome == up(204, 87)
    assert checker.urls == [monitor.url]
    check = await session.scalar(select(Check).where(Check.monitor_id == monitor.id))
    assert (check.scheduled_at, check.status_code) == (SCHEDULED_AT, 204)


async def test_no_database_connection_is_held_during_the_check(
    app_engine, session, sessions
):
    monitor = await add_monitor(session)
    in_use = []
    checker = FakeChecker(
        on_check=lambda: in_use.append(app_engine.sync_engine.pool.checkedout())
    )

    await run_check(sessions, checker, monitor_id=monitor.id, scheduled_at=SCHEDULED_AT)

    assert in_use == [0]


@pytest.mark.parametrize("state", ["deleted", "paused"])
async def test_deleted_or_paused_monitors_are_not_checked(session, sessions, state):
    monitor = await add_monitor(session, active=state != "paused")
    if state == "deleted":
        await session.delete(monitor)
        await session.commit()
    checker = FakeChecker()

    outcome = await run_check(
        sessions, checker, monitor_id=monitor.id, scheduled_at=SCHEDULED_AT
    )

    assert outcome is None
    assert checker.urls == []


def test_database_errors_never_show_query_parameters():
    # A failed insert would otherwise put error_detail (and the URL in it) in
    # the queue's logs and dead letters.
    assert get_engine().sync_engine.hide_parameters


async def test_logs_never_show_the_url_or_the_error_detail(session, sessions, caplog):
    caplog.set_level(logging.DEBUG)
    monitor = await add_monitor(session, url=SECRET_URL)
    detail = f"ConnectError: could not reach {SECRET_URL}"
    checker = FakeChecker(down("connection_error", detail))

    await run_check(sessions, checker, monitor_id=monitor.id, scheduled_at=SCHEDULED_AT)

    assert str(monitor.public_id) in caplog.text
    assert "connection_error" in caplog.text
    assert "s3cr3t-t0ken" not in caplog.text
    assert "example.com" not in caplog.text
