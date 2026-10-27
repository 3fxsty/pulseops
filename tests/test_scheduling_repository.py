"""Claiming due monitors, against the real database (row locks included)."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from pulseops.checker import CheckOutcome
from pulseops.db.models import Monitor
from pulseops.repositories.checks import record_check
from pulseops.repositories.scheduling import claim_due_monitors

pytestmark = pytest.mark.anyio


async def add_monitor(session, *, due_in: timedelta, interval=60, active=True):
    """A monitor whose next check is `due_in` from now (negative = overdue)."""
    monitor = Monitor(
        name="Example",
        url=f"https://example.com/{uuid.uuid4()}",
        interval_seconds=interval,
        is_active=active,
        next_check_at=func.now() + due_in,
    )
    session.add(monitor)
    await session.commit()
    await session.refresh(monitor)
    return monitor


async def reload(session, monitor: Monitor) -> Monitor:
    await session.refresh(monitor)
    return monitor


async def test_claims_a_due_monitor_and_moves_it_one_interval(session):
    monitor = await add_monitor(session, due_in=timedelta(seconds=-1))
    slot = monitor.next_check_at

    claimed = await claim_due_monitors(session)
    await session.commit()

    assert [(c.monitor_id, c.scheduled_at) for c in claimed] == [(monitor.id, slot)]
    monitor = await reload(session, monitor)
    assert monitor.next_check_at == slot + timedelta(seconds=60)


async def test_ignores_monitors_not_yet_due(session):
    await add_monitor(session, due_in=timedelta(seconds=30))

    assert await claim_due_monitors(session) == []


async def test_ignores_inactive_monitors(session):
    await add_monitor(session, due_in=timedelta(seconds=-1), active=False)

    assert await claim_due_monitors(session) == []


async def test_skips_missed_slots_but_keeps_the_rhythm(session):
    # Overdue by just over two intervals: the worker was down for a while.
    monitor = await add_monitor(session, due_in=timedelta(seconds=-125))
    slot = monitor.next_check_at

    claimed = await claim_due_monitors(session)
    await session.commit()

    # One check for the slot that was due, none for the ones missed...
    assert [c.scheduled_at for c in claimed] == [slot]
    # ...and the next slot is still on the monitor's original 60 s grid.
    monitor = await reload(session, monitor)
    assert monitor.next_check_at == slot + timedelta(seconds=180)
    assert monitor.next_check_at > await session.scalar(select(func.now()))


async def test_claims_at_most_the_batch_size_oldest_first(session):
    oldest = await add_monitor(session, due_in=timedelta(seconds=-30))
    older = await add_monitor(session, due_in=timedelta(seconds=-20))
    await add_monitor(session, due_in=timedelta(seconds=-10))

    claimed = await claim_due_monitors(session, limit=2)

    assert [c.monitor_id for c in claimed] == [oldest.id, older.id]


async def test_scheduling_does_not_touch_updated_at(session):
    monitor = await add_monitor(session, due_in=timedelta(seconds=-1))
    updated_at = monitor.updated_at

    await claim_due_monitors(session)
    await session.commit()

    assert (await reload(session, monitor)).updated_at == updated_at


async def test_two_schedulers_never_claim_the_same_monitor(app_engine, session):
    monitor = await add_monitor(session, due_in=timedelta(seconds=-1))
    slot = monitor.next_check_at
    sessions = async_sessionmaker(app_engine)

    async with sessions() as first, sessions() as second:
        assert len(await claim_due_monitors(first)) == 1
        # The row is locked by the first transaction: skipped, not waited on.
        assert await claim_due_monitors(second) == []
        await first.commit()
        # Committed: it is no longer due.
        assert await claim_due_monitors(second) == []

    monitor = await reload(session, monitor)
    assert monitor.next_check_at == slot + timedelta(seconds=60)


async def test_a_claimed_monitor_still_accepts_checks(app_engine, session):
    # While the scheduler holds its claim (enqueueing), a check that finishes
    # for that monitor must be stored without waiting for the commit.
    monitor = await add_monitor(session, due_in=timedelta(seconds=-1))
    sessions = async_sessionmaker(app_engine)
    outcome = CheckOutcome(is_up=True, status_code=200, response_time_ms=1)

    async with sessions() as scheduler, sessions() as worker:
        await claim_due_monitors(scheduler)
        stored = await asyncio.wait_for(
            record_check(
                worker,
                monitor_id=monitor.id,
                scheduled_at=monitor.next_check_at,
                outcome=outcome,
            ),
            timeout=2,
        )
        await scheduler.commit()

    assert stored is True


async def test_rolled_back_claim_is_claimed_again_with_the_same_slot(
    app_engine, session
):
    # What happens when enqueueing fails: rollback, and the next tick retries.
    monitor = await add_monitor(session, due_in=timedelta(seconds=-1))
    sessions = async_sessionmaker(app_engine)

    async with sessions() as first:
        await claim_due_monitors(first)
        await first.rollback()
    async with sessions() as second:
        claimed = await claim_due_monitors(second)

    assert [c.scheduled_at for c in claimed] == [monitor.next_check_at]
