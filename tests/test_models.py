import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from pulseops.db.models import ERROR_KINDS, Check, Monitor

pytestmark = pytest.mark.anyio

SCHEDULED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def make_monitor(**overrides) -> Monitor:
    fields = {
        "name": "Example",
        "url": f"https://example.com/{uuid.uuid4()}",
        "interval_seconds": 60,
    }
    return Monitor(**(fields | overrides))


async def create_monitor(session, **overrides) -> Monitor:
    monitor = make_monitor(**overrides)
    session.add(monitor)
    await session.commit()
    await session.refresh(monitor)
    return monitor


def check_values(monitor_id: int, **overrides) -> dict:
    fields = {
        "monitor_id": monitor_id,
        "scheduled_at": SCHEDULED_AT,
        "is_up": True,
        "status_code": 200,
        "response_time_ms": 120,
    }
    return fields | overrides


async def count_checks(session, monitor_id: int) -> int:
    query = select(func.count()).where(Check.monitor_id == monitor_id)
    return await session.scalar(query)


# --- monitors ---


async def test_monitor_gets_server_defaults(session):
    monitor = await create_monitor(session)

    assert monitor.public_id.version == 7
    assert monitor.is_active is True
    assert monitor.created_at.tzinfo is not None
    assert monitor.updated_at.tzinfo is not None


async def test_monitor_updated_at_changes_on_update(session):
    monitor = await create_monitor(session)
    before = monitor.updated_at

    monitor.name = "Renamed"
    await session.commit()
    await session.refresh(monitor)

    assert monitor.updated_at > before


@pytest.mark.parametrize("interval", [30, 86400])
async def test_monitor_interval_limits_are_accepted(session, interval):
    monitor = await create_monitor(session, interval_seconds=interval)

    assert monitor.interval_seconds == interval


@pytest.mark.parametrize("interval", [29, 86401])
async def test_monitor_interval_out_of_range_is_rejected(session, interval):
    session.add(make_monitor(interval_seconds=interval))

    with pytest.raises(IntegrityError, match="ck_monitors_interval_seconds_range"):
        await session.commit()


async def test_monitor_duplicate_url_is_rejected(session):
    await create_monitor(session, url="https://example.com")
    session.add(make_monitor(url="https://example.com"))

    with pytest.raises(IntegrityError, match="uq_monitors_url"):
        await session.commit()


async def test_deleting_monitor_deletes_its_checks(session):
    monitor = await create_monitor(session)
    await session.execute(
        insert(Check),
        [
            check_values(monitor.id, scheduled_at=SCHEDULED_AT),
            check_values(monitor.id, scheduled_at=datetime(2026, 1, 2, tzinfo=UTC)),
        ],
    )
    await session.commit()

    await session.delete(monitor)
    await session.commit()

    assert await count_checks(session, monitor.id) == 0


# --- checks ---


async def test_check_duplicate_schedule_is_rejected(session):
    monitor = await create_monitor(session)
    await session.execute(insert(Check).values(check_values(monitor.id)))

    with pytest.raises(IntegrityError, match="pk_checks"):
        await session.execute(insert(Check).values(check_values(monitor.id)))


async def test_check_redelivery_is_a_no_op_with_on_conflict(session):
    monitor = await create_monitor(session)
    statement = (
        pg_insert(Check).values(check_values(monitor.id)).on_conflict_do_nothing()
    )

    await session.execute(statement)
    await session.execute(statement)
    await session.commit()

    assert await count_checks(session, monitor.id) == 1


@pytest.mark.parametrize("error_kind", ERROR_KINDS)
async def test_check_accepts_every_known_error_kind(session, error_kind):
    monitor = await create_monitor(session)

    await session.execute(
        insert(Check).values(
            check_values(monitor.id, is_up=False, error_kind=error_kind)
        )
    )
    await session.commit()

    assert await count_checks(session, monitor.id) == 1


async def test_check_unknown_error_kind_is_rejected(session):
    monitor = await create_monitor(session)
    values = check_values(monitor.id, is_up=False, error_kind="too_slow")

    with pytest.raises(IntegrityError, match="ck_checks_error_kind_valid"):
        await session.execute(insert(Check).values(values))


@pytest.mark.parametrize(
    ("is_up", "error_kind"),
    [(True, "timeout"), (False, None)],
    ids=["up-with-error", "down-without-error"],
)
async def test_check_is_up_must_match_error_kind(session, is_up, error_kind):
    monitor = await create_monitor(session)
    values = check_values(monitor.id, is_up=is_up, error_kind=error_kind)

    with pytest.raises(IntegrityError, match="ck_checks_is_up_matches_error_kind"):
        await session.execute(insert(Check).values(values))


@pytest.mark.parametrize("status_code", [99, 600])
async def test_check_status_code_out_of_range_is_rejected(session, status_code):
    monitor = await create_monitor(session)
    values = check_values(monitor.id, status_code=status_code)

    with pytest.raises(IntegrityError, match="ck_checks_status_code_range"):
        await session.execute(insert(Check).values(values))


async def test_check_negative_response_time_is_rejected(session):
    monitor = await create_monitor(session)
    values = check_values(monitor.id, response_time_ms=-1)

    with pytest.raises(IntegrityError, match="ck_checks_response_time_ms_non_negative"):
        await session.execute(insert(Check).values(values))
