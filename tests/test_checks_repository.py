import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, insert, select

from pulseops.checker import CheckOutcome
from pulseops.db.models import Check, Monitor
from pulseops.repositories.checks import (
    check_stats,
    delete_expired_checks,
    latest_check,
    list_checks,
    record_check,
)

pytestmark = pytest.mark.anyio

SCHEDULED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
UP = CheckOutcome(is_up=True, status_code=200, response_time_ms=120)
DOWN = CheckOutcome(is_up=False, error_kind="timeout", error_detail="No response")


async def add_monitor(session) -> Monitor:
    monitor = Monitor(
        name="Example", url=f"https://example.com/{uuid.uuid4()}", interval_seconds=60
    )
    session.add(monitor)
    await session.commit()
    return monitor


async def stored_checks(session, monitor_id: int) -> list[Check]:
    query = select(Check).where(Check.monitor_id == monitor_id)
    return list(await session.scalars(query))


async def test_stores_the_outcome(session):
    monitor = await add_monitor(session)

    stored = await record_check(
        session, monitor_id=monitor.id, scheduled_at=SCHEDULED_AT, outcome=DOWN
    )

    assert stored is True
    [check] = await stored_checks(session, monitor.id)
    assert (check.scheduled_at, check.is_up, check.error_kind) == (
        SCHEDULED_AT,
        False,
        "timeout",
    )


async def test_the_same_check_twice_stores_one_row(session):
    # A re-delivered task: same monitor and slot, possibly another outcome.
    monitor = await add_monitor(session)
    first = await record_check(
        session, monitor_id=monitor.id, scheduled_at=SCHEDULED_AT, outcome=UP
    )
    second = await record_check(
        session, monitor_id=monitor.id, scheduled_at=SCHEDULED_AT, outcome=DOWN
    )

    assert (first, second) == (True, False)
    [check] = await stored_checks(session, monitor.id)
    assert check.is_up is True  # the first one wins


async def test_a_deleted_monitor_is_not_an_error(session):
    monitor = await add_monitor(session)
    await session.delete(monitor)
    await session.commit()

    stored = await record_check(
        session, monitor_id=monitor.id, scheduled_at=SCHEDULED_AT, outcome=UP
    )

    assert stored is False
    assert await session.scalar(select(func.count()).select_from(Check)) == 0


# --- reading and deleting history ---


async def add_check(session, monitor_id, *, ago, is_up=True, ms=100):
    """A check that was due `ago` before the database's now()."""
    await session.execute(
        insert(Check).values(
            monitor_id=monitor_id,
            scheduled_at=func.now() - ago,
            is_up=is_up,
            status_code=200 if is_up else None,
            response_time_ms=ms if is_up else None,
            error_kind=None if is_up else "timeout",
        )
    )
    await session.commit()


def minutes(n: int) -> timedelta:
    return timedelta(minutes=n)


async def test_list_checks_is_newest_first_and_pages_by_keyset(session):
    monitor = await add_monitor(session)
    for n in (1, 2, 3, 4, 5):
        await add_check(session, monitor.id, ago=minutes(n))

    first = await list_checks(session, monitor_id=monitor.id, limit=2)
    second = await list_checks(
        session, monitor_id=monitor.id, limit=2, before=first[-1].scheduled_at
    )
    everything = await list_checks(session, monitor_id=monitor.id, limit=10)

    assert [c.scheduled_at for c in first + second] == [
        c.scheduled_at for c in everything[:4]
    ]
    assert everything == sorted(everything, key=lambda c: c.scheduled_at, reverse=True)


async def test_list_checks_only_returns_that_monitor(session):
    mine, other = await add_monitor(session), await add_monitor(session)
    await add_check(session, other.id, ago=minutes(1))

    assert await list_checks(session, monitor_id=mine.id, limit=10) == []


async def test_latest_check(session):
    monitor = await add_monitor(session)
    assert await latest_check(session, monitor.id) is None

    await add_check(session, monitor.id, ago=minutes(5), is_up=True)
    await add_check(session, monitor.id, ago=minutes(1), is_up=False)

    assert (await latest_check(session, monitor.id)).is_up is False


async def test_stats_count_up_checks_and_latency_of_up_checks_only(session):
    monitor = await add_monitor(session)
    for n, ms in enumerate([100, 200, 300, 400], start=1):
        await add_check(session, monitor.id, ago=minutes(n), ms=ms)
    await add_check(session, monitor.id, ago=minutes(10), is_up=False)

    stats = await check_stats(session, monitor_id=monitor.id, period=timedelta(days=1))

    assert (stats.total, stats.up) == (5, 4)
    assert stats.avg_response_time_ms == 250
    # percentile_cont interpolates: 95 % of the way through 100..400.
    assert stats.p95_response_time_ms == pytest.approx(385)
    assert stats.until - stats.since == timedelta(days=1)


async def test_stats_only_count_the_period(session):
    monitor = await add_monitor(session)
    await add_check(session, monitor.id, ago=timedelta(hours=1))
    await add_check(session, monitor.id, ago=timedelta(hours=30), is_up=False)

    day = await check_stats(session, monitor_id=monitor.id, period=timedelta(days=1))
    week = await check_stats(session, monitor_id=monitor.id, period=timedelta(days=7))

    assert (day.total, day.up) == (1, 1)
    assert (week.total, week.up) == (2, 1)


async def test_stats_without_checks_have_no_latency(session):
    monitor = await add_monitor(session)

    stats = await check_stats(session, monitor_id=monitor.id, period=timedelta(days=7))

    assert (stats.total, stats.up) == (0, 0)
    assert stats.avg_response_time_ms is None
    assert stats.p95_response_time_ms is None


async def test_delete_expired_checks_keeps_recent_ones(session):
    monitor = await add_monitor(session)
    await add_check(session, monitor.id, ago=timedelta(days=31))
    await add_check(session, monitor.id, ago=timedelta(days=29))

    deleted = await delete_expired_checks(
        session, retention=timedelta(days=30), batch_size=100
    )

    assert deleted == 1
    [kept] = await stored_checks(session, monitor.id)
    assert kept.scheduled_at > await session.scalar(
        select(func.now() - timedelta(days=30))
    )


async def test_delete_expired_checks_deletes_one_batch_at_a_time(session):
    monitor = await add_monitor(session)
    for n in range(5):
        await add_check(session, monitor.id, ago=timedelta(days=40, minutes=n))

    first = await delete_expired_checks(
        session, retention=timedelta(days=30), batch_size=2
    )

    assert first == 2
    assert len(await stored_checks(session, monitor.id)) == 3
