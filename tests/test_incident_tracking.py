"""Storing a check updates its monitor's incidents (ADR-061, ADR-062)."""

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker

from pulseops import scheduling
from pulseops.checker.outcome import down, up
from pulseops.db.models import Check, Incident, Monitor, Notification
from pulseops.repositories import monitors as monitors_repository
from pulseops.repositories.incidents import INCIDENTS_LOCK_SPACE
from pulseops.repositories.monitors import (
    MonitorUrlConflictError,
    monitor_for_check_statement,
)
from pulseops.repositories.scheduling import claim_due_monitors
from pulseops.scheduling import run_check, store_check
from pulseops.security.validation import validate_monitor_url

pytestmark = pytest.mark.anyio

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
FAILED = down("http_error", "HTTP 503", status_code=503, response_time_ms=40)
OK = up(200, 40)
# Long enough for a blocked statement to show it is waiting.
WAIT = 0.3


def slot(n: int) -> datetime:
    return T0 + timedelta(seconds=60 * n)


@pytest.fixture
def sessions(app_engine):
    return async_sessionmaker(app_engine, expire_on_commit=False)


async def add_monitor(session, **overrides) -> Monitor:
    fields = {
        "name": "Example",
        "url": f"https://example.com/{uuid.uuid4()}",
        "interval_seconds": 60,
        "next_check_at": func.now() - timedelta(seconds=1),
    }
    monitor = Monitor(**(fields | overrides))
    session.add(monitor)
    await session.commit()
    await session.refresh(monitor)
    await session.commit()  # hand the connection back to the pool
    return monitor


async def store(sessions, monitor_id: int, at: datetime, outcome=FAILED):
    async with sessions() as session:
        return await store_check(
            session, monitor_id=monitor_id, scheduled_at=at, outcome=outcome
        )


async def incidents_of(sessions, monitor_id: int) -> list[Incident]:
    async with sessions() as session:
        query = (
            select(Incident)
            .where(Incident.monitor_id == monitor_id)
            .order_by(Incident.started_at)
        )
        return list(await session.scalars(query))


async def alerts_of(sessions, monitor_id: int) -> list[str]:
    async with sessions() as session:
        query = (
            select(Notification.kind)
            .join(Incident)
            .where(Incident.monitor_id == monitor_id, Notification.status == "pending")
            .order_by(Notification.id)
        )
        return list(await session.scalars(query))


@pytest.fixture
def monitoring_slowly(monkeypatch):
    """store_check pauses between evaluating incidents and committing."""
    evaluate = scheduling._track_incidents

    async def slow_evaluate(*args):
        event = await evaluate(*args)
        await asyncio.sleep(WAIT)
        return event

    monkeypatch.setattr(scheduling, "_track_incidents", slow_evaluate)


@contextlib.asynccontextmanager
async def holding_the_lock(app_engine, monitor_id: int, *, also_key_share=False):
    """Another transaction holds the monitor's incidents lock until the block
    ends, as store_check does while it evaluates."""
    async with app_engine.connect() as connection:
        await connection.execute(
            text("SELECT pg_advisory_xact_lock(:space, :id)"),
            {"space": INCIDENTS_LOCK_SPACE, "id": monitor_id},
        )
        if also_key_share:
            await connection.execute(monitor_for_check_statement(monitor_id))
        yield
        await connection.commit()


# --- opening and closing ---


async def test_two_failures_open_an_incident_and_queue_its_alert(session, sessions):
    monitor = await add_monitor(session)

    first = await store(sessions, monitor.id, slot(0))
    second = await store(sessions, monitor.id, slot(1))

    assert (first, second) == ((True, None), (True, "opened"))
    [incident] = await incidents_of(sessions, monitor.id)
    assert (incident.started_at, incident.error_kind, incident.status_code) == (
        slot(0),
        "http_error",
        503,
    )
    assert incident.resolved_at is None
    assert await alerts_of(sessions, monitor.id) == ["opened"]


async def test_two_successes_resolve_it_and_queue_the_resolved_alert(session, sessions):
    monitor = await add_monitor(session)
    for n, outcome in enumerate([FAILED, FAILED, OK]):
        await store(sessions, monitor.id, slot(n), outcome)

    assert await store(sessions, monitor.id, slot(3), OK) == (True, "resolved")

    [incident] = await incidents_of(sessions, monitor.id)
    assert (incident.resolved_at, incident.resolution) == (slot(2), "recovered")
    assert await alerts_of(sessions, monitor.id) == ["opened", "resolved"]


async def test_a_redelivered_check_is_not_counted_twice(session, sessions):
    monitor = await add_monitor(session)

    first = await store(sessions, monitor.id, slot(0))
    again = await store(sessions, monitor.id, slot(0))

    assert (first, again) == ((True, None), (False, None))
    assert await incidents_of(sessions, monitor.id) == []


async def test_a_late_check_is_stored_but_decides_nothing(session, sessions):
    # slot 1 arrives before slot 0 (e.g. a retried task). The late one is kept
    # in the history but must not open the incident: a newer check decided.
    monitor = await add_monitor(session)
    await store(sessions, monitor.id, slot(1))

    assert await store(sessions, monitor.id, slot(0)) == (True, None)
    assert await incidents_of(sessions, monitor.id) == []

    # The next check sees the whole streak, and the incident starts at its
    # real first failure.
    assert await store(sessions, monitor.id, slot(2)) == (True, "opened")
    [incident] = await incidents_of(sessions, monitor.id)
    assert incident.started_at == slot(0)


async def test_a_paused_monitor_is_stored_but_not_evaluated(session, sessions):
    # Paused while its check was running.
    monitor = await add_monitor(session, is_active=False)

    results = [await store(sessions, monitor.id, slot(n)) for n in range(2)]

    assert results == [(True, None), (True, None)]
    assert await incidents_of(sessions, monitor.id) == []


async def test_a_deleted_monitor_stores_nothing(session, sessions):
    monitor = await add_monitor(session)
    await session.delete(monitor)
    await session.commit()

    assert await store(sessions, monitor.id, slot(0)) == (False, None)
    assert await session.scalar(select(func.count()).select_from(Check)) == 0


# --- one monitor at a time ---


async def test_checks_of_one_monitor_take_turns(app_engine, session, sessions):
    monitor = await add_monitor(session)
    other = await add_monitor(session)

    async with holding_the_lock(app_engine, monitor.id):
        waiting = asyncio.create_task(store(sessions, monitor.id, slot(0)))
        await asyncio.sleep(WAIT)
        assert not waiting.done()
        # Another monitor never waits for it.
        assert await asyncio.wait_for(store(sessions, other.id, slot(0)), 2) == (
            True,
            None,
        )

    assert await asyncio.wait_for(waiting, 2) == (True, None)


async def test_two_failures_at_the_same_time_open_one_incident(
    session, sessions, monitoring_slowly
):
    # Each store waits between its evaluation and its commit, so both would
    # evaluate before either commits: without the lock, each would see only
    # its own failure and the two together would open nothing.
    monitor = await add_monitor(session)

    first = asyncio.create_task(store(sessions, monitor.id, slot(0)))
    await asyncio.sleep(WAIT / 3)  # the first one takes the lock
    second = asyncio.create_task(store(sessions, monitor.id, slot(1)))
    results = await asyncio.wait_for(asyncio.gather(first, second), 5)

    assert results == [(True, None), (True, "opened")]
    [incident] = await incidents_of(sessions, monitor.id)
    assert incident.started_at == slot(0)


async def test_the_scheduler_is_not_blocked_by_a_check_being_stored(
    app_engine, session, sessions
):
    monitor = await add_monitor(session)

    async with holding_the_lock(app_engine, monitor.id, also_key_share=True):
        async with sessions() as scheduler:
            claimed = await asyncio.wait_for(claim_due_monitors(scheduler), 2)
            await scheduler.commit()

    assert [d.monitor_id for d in claimed] == [monitor.id]


def test_the_monitor_row_lock_is_key_share():
    # SQLAlchemy renders FOR KEY SHARE only with read=True and key_share=True;
    # key_share alone would be the stronger FOR NO KEY UPDATE.
    sql = str(monitor_for_check_statement(1).compile(dialect=postgresql.dialect()))

    assert sql.endswith("FOR KEY SHARE")


# --- pausing and changing the URL (ADR-062) ---


async def open_incident_for(session, sessions) -> Monitor:
    monitor = await add_monitor(session)
    await store(sessions, monitor.id, slot(0))
    await store(sessions, monitor.id, slot(1))
    return monitor


async def validated(url: str):
    return await validate_monitor_url(url, allow_private_targets=False)


async def test_pausing_ends_the_incident_without_a_resolved_alert(session, sessions):
    monitor = await open_incident_for(session, sessions)

    await monitors_repository.update_monitor(session, monitor, {"is_active": False})

    [incident] = await incidents_of(sessions, monitor.id)
    assert incident.resolution == "paused"
    assert incident.resolved_at > incident.started_at
    assert await alerts_of(sessions, monitor.id) == ["opened"]


async def test_a_new_url_ends_it_as_monitor_changed(session, sessions, fake_dns):
    monitor = await open_incident_for(session, sessions)
    new_url = await validated(f"https://example.org/{uuid.uuid4()}")

    await monitors_repository.update_monitor(session, monitor, {"url": new_url})

    [incident] = await incidents_of(sessions, monitor.id)
    assert incident.resolution == "monitor_changed"
    assert await alerts_of(sessions, monitor.id) == ["opened"]


@pytest.mark.parametrize(
    "changes",
    [{"name": "Renamed"}, {"interval_seconds": 300}, {"is_active": True}],
    ids=["rename", "interval", "still-active"],
)
async def test_other_edits_keep_it_open(session, sessions, changes):
    monitor = await open_incident_for(session, sessions)

    await monitors_repository.update_monitor(session, monitor, changes)

    [incident] = await incidents_of(sessions, monitor.id)
    assert incident.resolved_at is None


async def test_a_rejected_url_change_keeps_it_open(session, sessions, fake_dns):
    taken = await validated(f"https://example.org/{uuid.uuid4()}")
    await add_monitor(session, url=taken.value)
    monitor = await open_incident_for(session, sessions)
    monitor_id = monitor.id  # the rollback expires the loaded monitor

    with pytest.raises(MonitorUrlConflictError):
        await monitors_repository.update_monitor(session, monitor, {"url": taken})

    [incident] = await incidents_of(sessions, monitor_id)
    assert incident.resolved_at is None


async def test_checks_from_before_a_url_change_never_reopen_it(
    session, sessions, fake_dns
):
    monitor = await open_incident_for(session, sessions)
    new_url = await validated(f"https://example.org/{uuid.uuid4()}")
    await monitors_repository.update_monitor(session, monitor, {"url": new_url})

    # A check of the old URL, still in flight during the change: with slot 1
    # it would make two failures in a row, but both predate the change.
    assert await store(sessions, monitor.id, slot(2)) == (True, None)
    assert len(await incidents_of(sessions, monitor.id)) == 1


async def test_pausing_waits_for_a_check_being_evaluated(app_engine, session):
    monitor = await add_monitor(session)

    async with holding_the_lock(app_engine, monitor.id):
        pausing = asyncio.create_task(
            monitors_repository.update_monitor(session, monitor, {"is_active": False})
        )
        await asyncio.sleep(WAIT)
        assert not pausing.done()

    await asyncio.wait_for(pausing, 2)


# --- the worker's log ---


class FailingChecker:
    async def check(self, url):
        return FAILED


async def test_the_log_says_when_an_incident_opens(session, sessions, caplog):
    caplog.set_level(logging.INFO)
    monitor = await add_monitor(session)

    for n in range(2):
        await run_check(
            sessions, FailingChecker(), monitor_id=monitor.id, scheduled_at=slot(n)
        )

    assert "incident=opened" in caplog.text
    assert monitor.url not in caplog.text
