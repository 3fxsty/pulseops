"""Retention: batch by batch, recent checks kept, within a time budget."""

import logging
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from pulseops.db.models import Check, Incident, Monitor, Notification
from pulseops.retention import purge_expired_checks, purge_expired_incidents

pytestmark = pytest.mark.anyio


@pytest.fixture
def sessions(app_engine):
    return async_sessionmaker(app_engine, expire_on_commit=False)


@pytest.fixture
async def monitor_id(session) -> int:
    monitor = Monitor(
        name="Example", url=f"https://example.com/{uuid.uuid4()}", interval_seconds=60
    )
    session.add(monitor)
    await session.commit()
    return monitor.id


async def add_checks(session, monitor_id, *, days_ago, count):
    for n in range(count):
        await session.execute(
            insert(Check).values(
                monitor_id=monitor_id,
                scheduled_at=func.now() - timedelta(days=days_ago, minutes=n),
                is_up=True,
                status_code=200,
                response_time_ms=100,
            )
        )
    await session.commit()


async def count_checks(session) -> int:
    return await session.scalar(select(func.count()).select_from(Check))


async def test_deletes_every_expired_batch_and_keeps_recent_checks(
    session, sessions, monitor_id
):
    await add_checks(session, monitor_id, days_ago=31, count=5)
    await add_checks(session, monitor_id, days_ago=29, count=2)

    deleted = await purge_expired_checks(sessions, batch_size=2)

    assert deleted == 5
    assert await count_checks(session) == 2


async def test_stops_at_the_time_limit_and_finishes_next_run(
    session, sessions, monitor_id, caplog
):
    caplog.set_level(logging.INFO)
    await add_checks(session, monitor_id, days_ago=40, count=5)
    ticks = iter(range(100))  # a clock that moves one second per reading

    first = await purge_expired_checks(
        sessions, batch_size=2, max_seconds=1, clock=lambda: next(ticks)
    )

    # One batch, then the budget is spent: the rest waits for the next run.
    assert first == 2
    assert await count_checks(session) == 3
    assert "time limit reached" in caplog.text

    second = await purge_expired_checks(sessions, batch_size=2)

    assert second == 3
    assert await count_checks(session) == 0


async def test_nothing_to_delete(sessions, monitor_id):
    assert await purge_expired_checks(sessions) == 0


# --- incidents (ADR-062): kept a year ---


async def add_incident(session, monitor_id, *, started_days_ago, resolved_days_ago):
    incident = Incident(
        monitor_id=monitor_id,
        started_at=func.now() - timedelta(days=started_days_ago),
        resolved_at=None
        if resolved_days_ago is None
        else func.now() - timedelta(days=resolved_days_ago),
        resolution=None if resolved_days_ago is None else "recovered",
        error_kind="timeout",
    )
    session.add(incident)
    await session.flush()
    session.add(Notification(incident_id=incident.id, kind="opened"))
    await session.commit()
    return incident.id


async def test_incidents_resolved_over_a_year_ago_are_deleted(
    session, sessions, monitor_id
):
    old = await add_incident(
        session, monitor_id, started_days_ago=367, resolved_days_ago=366
    )
    recent = await add_incident(
        session, monitor_id, started_days_ago=365, resolved_days_ago=364
    )
    still_open = await add_incident(
        session, monitor_id, started_days_ago=730, resolved_days_ago=None
    )

    assert await purge_expired_incidents(sessions) == 1

    remaining = set(await session.scalars(select(Incident.id)))
    assert remaining == {recent, still_open}
    # Its alert went with it (ON DELETE CASCADE).
    alerts = set(await session.scalars(select(Notification.incident_id)))
    assert old not in alerts
