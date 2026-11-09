"""The incidents and notifications tables enforce their own rules (ADR-062, ADR-063)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from pulseops.db.models import (
    INCIDENT_RESOLUTIONS,
    NOTIFICATION_STATUSES,
    Incident,
    Monitor,
    Notification,
)

pytestmark = pytest.mark.anyio

STARTED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LATER = STARTED_AT + timedelta(minutes=5)


async def create_monitor(session) -> Monitor:
    monitor = Monitor(
        name="Example",
        url=f"https://example.com/{uuid.uuid4()}",
        interval_seconds=60,
    )
    session.add(monitor)
    await session.commit()
    return monitor


def make_incident(monitor_id: int, **overrides) -> Incident:
    fields = {
        "monitor_id": monitor_id,
        "started_at": STARTED_AT,
        "error_kind": "http_error",
        "status_code": 503,
    }
    return Incident(**(fields | overrides))


async def create_incident(session, **overrides) -> Incident:
    monitor = await create_monitor(session)
    incident = make_incident(monitor.id, **overrides)
    session.add(incident)
    await session.commit()
    return incident


# --- incidents ---


async def test_incident_gets_server_defaults(session):
    incident = await create_incident(session)

    assert incident.public_id.version == 7
    assert incident.resolved_at is None
    assert incident.resolution is None


async def test_only_one_open_incident_per_monitor(session):
    incident = await create_incident(session)
    session.add(make_incident(incident.monitor_id, started_at=LATER))

    with pytest.raises(IntegrityError, match="ix_incidents_monitor_id_open"):
        await session.commit()


async def test_a_resolved_incident_does_not_block_a_new_one(session):
    incident = await create_incident(session, resolved_at=LATER, resolution="recovered")
    session.add(make_incident(incident.monitor_id, started_at=LATER))

    await session.commit()


async def test_two_monitors_can_each_have_an_open_incident(session):
    await create_incident(session)
    await create_incident(session)


async def test_two_incidents_cannot_start_at_the_same_check(session):
    incident = await create_incident(session, resolved_at=LATER, resolution="recovered")
    session.add(
        make_incident(incident.monitor_id, resolved_at=LATER, resolution="recovered")
    )

    with pytest.raises(IntegrityError, match="uq_incidents_monitor_id_started_at"):
        await session.commit()


@pytest.mark.parametrize("resolution", INCIDENT_RESOLUTIONS)
async def test_incident_accepts_every_known_resolution(session, resolution):
    incident = await create_incident(session, resolved_at=LATER, resolution=resolution)

    assert incident.resolution == resolution


async def test_incident_unknown_resolution_is_rejected(session):
    monitor = await create_monitor(session)
    session.add(make_incident(monitor.id, resolved_at=LATER, resolution="fixed"))

    with pytest.raises(IntegrityError, match="ck_incidents_resolution_valid"):
        await session.commit()


@pytest.mark.parametrize(
    ("resolved_at", "resolution"),
    [(LATER, None), (None, "recovered")],
    ids=["resolved-without-resolution", "resolution-while-open"],
)
async def test_resolved_at_and_resolution_go_together(session, resolved_at, resolution):
    monitor = await create_monitor(session)
    session.add(
        make_incident(monitor.id, resolved_at=resolved_at, resolution=resolution)
    )

    with pytest.raises(
        IntegrityError, match="ck_incidents_resolved_at_matches_resolution"
    ):
        await session.commit()


async def test_incident_cannot_end_before_it_starts(session):
    monitor = await create_monitor(session)
    session.add(
        make_incident(
            monitor.id,
            resolved_at=STARTED_AT - timedelta(seconds=1),
            resolution="recovered",
        )
    )

    with pytest.raises(IntegrityError, match="ck_incidents_resolved_after_started"):
        await session.commit()


async def test_incident_unknown_error_kind_is_rejected(session):
    monitor = await create_monitor(session)
    session.add(make_incident(monitor.id, error_kind="too_slow"))

    with pytest.raises(IntegrityError, match="ck_incidents_error_kind_valid"):
        await session.commit()


@pytest.mark.parametrize("status_code", [99, 600])
async def test_incident_status_code_out_of_range_is_rejected(session, status_code):
    monitor = await create_monitor(session)
    session.add(make_incident(monitor.id, status_code=status_code))

    with pytest.raises(IntegrityError, match="ck_incidents_status_code_range"):
        await session.commit()


async def test_deleting_a_monitor_deletes_its_incidents_and_alerts(session):
    incident = await create_incident(session)
    session.add(Notification(incident_id=incident.id, kind="opened"))
    await session.commit()
    monitor = await session.get(Monitor, incident.monitor_id)

    await session.delete(monitor)
    await session.commit()

    assert await session.scalar(select(func.count()).select_from(Incident)) == 0
    assert await session.scalar(select(func.count()).select_from(Notification)) == 0


# --- notifications ---


async def create_notification(session, **overrides) -> Notification:
    incident = await create_incident(session)
    notification = Notification(
        **({"incident_id": incident.id, "kind": "opened"} | overrides)
    )
    session.add(notification)
    await session.commit()
    await session.refresh(notification)
    return notification


async def test_notification_starts_pending_and_due_now(session):
    notification = await create_notification(session)

    assert notification.status == "pending"
    assert notification.attempts == 0
    assert notification.next_attempt_at == notification.created_at
    assert notification.finished_at is None


async def test_one_alert_of_each_kind_per_incident(session):
    notification = await create_notification(session)
    session.add(Notification(incident_id=notification.incident_id, kind="resolved"))
    await session.commit()

    session.add(Notification(incident_id=notification.incident_id, kind="opened"))
    with pytest.raises(IntegrityError, match="uq_notifications_incident_id_kind"):
        await session.commit()


async def test_notification_unknown_kind_is_rejected(session):
    incident = await create_incident(session)
    session.add(Notification(incident_id=incident.id, kind="reminder"))

    with pytest.raises(IntegrityError, match="ck_notifications_kind_valid"):
        await session.commit()


async def test_notification_unknown_status_is_rejected(session):
    incident = await create_incident(session)
    session.add(
        Notification(
            incident_id=incident.id, kind="opened", status="lost", finished_at=LATER
        )
    )

    with pytest.raises(IntegrityError, match="ck_notifications_status_valid"):
        await session.commit()


@pytest.mark.parametrize("status", [s for s in NOTIFICATION_STATUSES if s != "pending"])
async def test_a_finished_notification_has_a_finish_time(session, status):
    incident = await create_incident(session)
    session.add(Notification(incident_id=incident.id, kind="opened", status=status))

    with pytest.raises(
        IntegrityError, match="ck_notifications_finished_at_matches_status"
    ):
        await session.commit()


async def test_a_pending_notification_has_no_finish_time(session):
    incident = await create_incident(session)
    session.add(Notification(incident_id=incident.id, kind="opened", finished_at=LATER))

    with pytest.raises(
        IntegrityError, match="ck_notifications_finished_at_matches_status"
    ):
        await session.commit()


async def test_notification_negative_attempts_are_rejected(session):
    incident = await create_incident(session)
    session.add(Notification(incident_id=incident.id, kind="opened", attempts=-1))

    with pytest.raises(IntegrityError, match="ck_notifications_attempts_non_negative"):
        await session.commit()
