"""Incident endpoints and open_incident in /stats (ADR-069), against the real
test database."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest
from sqlalchemy import select

from pulseops.api.cursors import encode_cursor
from pulseops.api.schemas import Resolution
from pulseops.db.models import INCIDENT_RESOLUTIONS, Incident, Monitor

pytestmark = pytest.mark.anyio

MONITORS = "/api/v1/monitors"
INCIDENTS = "/api/v1/incidents"
UNKNOWN_ID = "01a17ab7-3cce-7875-acce-000000000000"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
INCIDENT_FIELDS = {
    "id",
    "started_at",
    "resolved_at",
    "error_kind",
    "status_code",
    "resolution",
}


async def create_monitor(client, session, name="Example"):
    """A monitor created through the API, with its internal id for inserts."""
    body = {
        "name": name,
        "url": f"https://example.com/{uuid.uuid4()}",
        "interval_seconds": 60,
    }
    created = (await client.post(MONITORS, json=body)).json()
    internal_id = await session.scalar(
        select(Monitor.id).where(Monitor.public_id == created["id"])
    )
    return {"id": created["id"], "internal_id": internal_id, "name": name}


@pytest.fixture
async def monitor(client, session):
    return await create_monitor(client, session)


async def add_incident(session, monitor, *, hours, open_=False) -> str:
    """An incident that started `hours` after T0, resolved 5 minutes later."""
    started = T0 + timedelta(hours=hours)
    incident = Incident(
        monitor_id=monitor["internal_id"],
        started_at=started,
        resolved_at=None if open_ else started + timedelta(minutes=5),
        resolution=None if open_ else "recovered",
        error_kind="http_error",
        status_code=503,
    )
    session.add(incident)
    await session.commit()
    return str(incident.public_id)


def monitor_incidents(monitor):
    return f"{MONITORS}/{monitor['id']}/incidents"


async def every_page(client, url, **params) -> list[dict]:
    """Follow next_cursor to the end, one item per page."""
    items, cursor = [], None
    while True:
        query = {**params, "limit": 1} | ({"cursor": cursor} if cursor else {})
        body = (await client.get(url, params=query)).json()
        items += body["items"]
        cursor = body["next_cursor"]
        if cursor is None:
            return items


# --- one monitor's incidents ---


async def test_a_monitor_without_incidents_has_an_empty_list(client, monitor):
    response = await client.get(monitor_incidents(monitor))

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


async def test_incidents_have_exactly_the_approved_fields(client, session, monitor):
    resolved = await add_incident(session, monitor, hours=0)
    still_open = await add_incident(session, monitor, hours=1, open_=True)

    items = (await client.get(monitor_incidents(monitor))).json()["items"]

    assert items == [
        {
            "id": still_open,
            "started_at": "2026-11-01T13:00:00Z",
            "resolved_at": None,
            "error_kind": "http_error",
            "status_code": 503,
            "resolution": None,
        },
        {
            "id": resolved,
            "started_at": "2026-11-01T12:00:00Z",
            "resolved_at": "2026-11-01T12:05:00Z",
            "error_kind": "http_error",
            "status_code": 503,
            "resolution": "recovered",
        },
    ]


async def test_pages_cover_every_incident_once_newest_first(client, session, monitor):
    ids = [await add_incident(session, monitor, hours=h) for h in range(3)]

    items = await every_page(client, monitor_incidents(monitor))

    assert [i["id"] for i in items] == ids[::-1]


async def test_only_that_monitors_incidents(client, session, monitor):
    other = await create_monitor(client, session, name="Other")
    await add_incident(session, other, hours=0)

    assert (await client.get(monitor_incidents(monitor))).json()["items"] == []


async def test_a_cursor_never_reaches_another_monitor(client, session, monitor):
    # The monitor always comes from the URL, never from the cursor.
    other = await create_monitor(client, session, name="Other")
    for h in range(2):
        await add_incident(session, other, hours=h)
    cursor = (await client.get(monitor_incidents(other), params={"limit": 1})).json()[
        "next_cursor"
    ]

    response = await client.get(monitor_incidents(monitor), params={"cursor": cursor})

    assert response.json()["items"] == []


# --- across monitors ---


async def test_the_list_across_monitors_says_whose_incident_it_is(
    client, session, monitor
):
    incident = await add_incident(session, monitor, hours=0, open_=True)

    [item] = (await client.get(INCIDENTS)).json()["items"]

    assert set(item) == INCIDENT_FIELDS | {"monitor"}
    assert item["id"] == incident
    assert item["monitor"] == {"id": monitor["id"], "name": "Example"}


@pytest.mark.parametrize(
    ("state", "expected"),
    [("open", ["open"]), ("resolved", ["resolved"]), (None, ["open", "resolved"])],
)
async def test_state_filters_open_and_resolved(
    client, session, monitor, state, expected
):
    ids = {
        "resolved": await add_incident(session, monitor, hours=0),
        "open": await add_incident(session, monitor, hours=1, open_=True),
    }
    params = {"state": state} if state else {}

    items = (await client.get(INCIDENTS, params=params)).json()["items"]

    assert [i["id"] for i in items] == [ids[name] for name in expected]


async def test_an_unknown_state_is_422(client):
    response = await client.get(INCIDENTS, params={"state": "closed"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert [e["loc"] for e in body["errors"]] == [["query", "state"]]


async def test_incidents_starting_at_the_same_moment_are_each_listed_once(
    client, session, monitor
):
    # Two monitors, same start: the incident id breaks the tie in the cursor.
    other = await create_monitor(client, session, name="Other")
    ids = {
        await add_incident(session, monitor, hours=0),
        await add_incident(session, other, hours=0),
    }

    items = await every_page(client, INCIDENTS)

    assert sorted(i["id"] for i in items) == sorted(ids)


# --- cursors, limits, access ---


@pytest.mark.parametrize(
    "cursor",
    ["not-a-cursor", encode_cursor(T0)],  # a check-history cursor does not fit
    ids=["forged", "history-cursor"],
)
async def test_a_foreign_cursor_is_422_without_echoing_it(client, monitor, cursor):
    for url in (INCIDENTS, monitor_incidents(monitor)):
        response = await client.get(url, params={"cursor": cursor})

        assert response.status_code == 422
        assert response.json()["code"] == "invalid_cursor"
        assert cursor not in response.text


@pytest.mark.parametrize("limit", [0, 101])
async def test_limit_is_bounded(client, monitor, limit):
    for url in (INCIDENTS, monitor_incidents(monitor)):
        assert (await client.get(url, params={"limit": limit})).status_code == 422


async def test_unknown_monitor_is_404(client):
    response = await client.get(f"{MONITORS}/{UNKNOWN_ID}/incidents")

    assert response.status_code == 404
    assert response.json()["code"] == "monitor_not_found"


async def test_api_key_is_required(client, monitor):
    for url in (INCIDENTS, monitor_incidents(monitor)):
        response = await client.get(url, headers={"X-API-Key": ""})

        assert response.status_code == 401


async def test_internal_ids_are_never_exposed(client, session, monitor):
    await add_incident(session, monitor, hours=0)

    for url in (INCIDENTS, monitor_incidents(monitor)):
        body = (await client.get(url)).json()
        [item] = body["items"]
        assert "monitor_id" not in response_keys(body)
        # Public UUIDs only, never the integer keys.
        assert uuid.UUID(item["id"]).version == 7
        if "monitor" in item:
            assert uuid.UUID(item["monitor"]["id"]).version == 7


def response_keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in response_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in response_keys(v)}
    return set()


def test_api_resolutions_match_the_database():
    assert set(get_args(Resolution)) == set(INCIDENT_RESOLUTIONS)


# --- /stats ---


async def test_stats_show_the_open_incident(client, session, monitor):
    await add_incident(session, monitor, hours=0)
    open_id = await add_incident(session, monitor, hours=1, open_=True)

    stats = (await client.get(f"{MONITORS}/{monitor['id']}/stats")).json()

    assert stats["open_incident"] == {
        "id": open_id,
        "started_at": "2026-11-01T13:00:00Z",
        "error_kind": "http_error",
        "status_code": 503,
    }


async def test_stats_without_an_open_incident_say_null(client, session, monitor):
    await add_incident(session, monitor, hours=0)

    stats = (await client.get(f"{MONITORS}/{monitor['id']}/stats")).json()

    assert stats["open_incident"] is None
