"""Editing a monitor: which changes bring its next check forward to now."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from pulseops.repositories import monitors as repository
from pulseops.security.validation import validate_monitor_url

pytestmark = pytest.mark.anyio

FAR_AWAY = timedelta(days=1)


async def validated(url: str):
    return await validate_monitor_url(url, allow_private_targets=False)


@pytest.fixture
async def monitor(session, fake_dns):
    """A monitor whose next check is a day away."""
    monitor = await repository.create_monitor(
        session,
        name="Example",
        url=await validated(f"https://example.com/{uuid.uuid4()}"),
        interval_seconds=86400,
        is_active=True,
    )
    monitor.next_check_at = func.now() + FAR_AWAY
    await session.commit()
    return monitor


async def is_due_now(session, monitor) -> bool:
    now = await session.scalar(select(func.now()))
    return monitor.next_check_at <= now


async def test_a_new_monitor_is_checked_right_away(session, fake_dns):
    monitor = await repository.create_monitor(
        session,
        name="Example",
        url=await validated("https://example.com/new"),
        interval_seconds=60,
        is_active=True,
    )

    assert await is_due_now(session, monitor)


async def test_new_interval_is_checked_right_away(session, monitor):
    await repository.update_monitor(session, monitor, {"interval_seconds": 30})

    assert await is_due_now(session, monitor)


async def test_new_url_is_checked_right_away(session, monitor):
    url = await validated("https://example.com/other")
    await repository.update_monitor(session, monitor, {"url": url})

    assert await is_due_now(session, monitor)


async def test_reactivated_monitor_is_checked_right_away(session, monitor):
    await repository.update_monitor(session, monitor, {"is_active": False})
    assert not await is_due_now(session, monitor)

    await repository.update_monitor(session, monitor, {"is_active": True})

    assert await is_due_now(session, monitor)


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "Renamed"},
        {"is_active": False},
        {"is_active": True},  # already active
        {"interval_seconds": 86400},  # same value
    ],
)
async def test_other_changes_keep_the_schedule(session, monitor, changes):
    await repository.update_monitor(session, monitor, changes)

    assert not await is_due_now(session, monitor)
