import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from pulseops.checker import CheckOutcome
from pulseops.db.models import Check, Monitor
from pulseops.repositories.checks import record_check

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
