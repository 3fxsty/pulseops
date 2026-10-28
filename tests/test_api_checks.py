"""History and stats endpoints, against the real test database."""

from datetime import timedelta
from typing import get_args

import pytest
from sqlalchemy import func, insert, select

from pulseops.api.cursors import encode_cursor
from pulseops.api.schemas import ErrorKind
from pulseops.db.models import ERROR_KINDS, Check, Monitor

pytestmark = pytest.mark.anyio

MONITORS = "/api/v1/monitors"
UNKNOWN_ID = "01a17ab7-3cce-7875-acce-000000000000"
CHECK_FIELDS = {
    "scheduled_at",
    "is_up",
    "status_code",
    "response_time_ms",
    "error_kind",
    "error_detail",
}


@pytest.fixture
async def monitor(client, session):
    """A monitor created through the API, with its internal id for inserts."""
    body = {"name": "Example", "url": "https://example.com", "interval_seconds": 60}
    created = (await client.post(MONITORS, json=body)).json()
    internal_id = await session.scalar(
        select(Monitor.id).where(Monitor.public_id == created["id"])
    )
    return {"id": created["id"], "internal_id": internal_id}


async def add_check(session, monitor, *, ago, is_up=True, ms=100):
    await session.execute(
        insert(Check).values(
            monitor_id=monitor["internal_id"],
            scheduled_at=func.now() - ago,
            is_up=is_up,
            status_code=200 if is_up else 503,
            response_time_ms=ms,
            error_kind=None if is_up else "http_error",
            error_detail=None if is_up else "HTTP 503",
        )
    )
    await session.commit()


def checks_url(monitor, **params):
    return f"{MONITORS}/{monitor['id']}/checks", params


def stats_url(monitor):
    return f"{MONITORS}/{monitor['id']}/stats"


# --- /checks ---


async def test_history_of_a_monitor_without_checks_is_empty(client, monitor):
    url, _ = checks_url(monitor)

    response = await client.get(url)

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


async def test_history_items_have_exactly_the_public_fields(client, session, monitor):
    await add_check(session, monitor, ago=timedelta(minutes=1), is_up=False)
    url, _ = checks_url(monitor)

    [item] = (await client.get(url)).json()["items"]

    assert set(item) == CHECK_FIELDS
    assert (item["error_kind"], item["error_detail"]) == ("http_error", "HTTP 503")


async def test_history_pages_cover_every_check_once_in_order(client, session, monitor):
    for n in range(5):
        await add_check(session, monitor, ago=timedelta(minutes=n + 1))
    url, _ = checks_url(monitor)
    seen, cursor = [], None

    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = (await client.get(url, params=params)).json()
        seen += [item["scheduled_at"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == 5
    assert seen == sorted(seen, reverse=True)


async def test_new_checks_do_not_shift_the_next_page(client, session, monitor):
    for n in range(4):
        await add_check(session, monitor, ago=timedelta(minutes=n + 1))
    url, _ = checks_url(monitor)
    first = (await client.get(url, params={"limit": 2})).json()

    # A check arrives while the client reads page one.
    await add_check(session, monitor, ago=timedelta(seconds=1))
    second = (
        await client.get(url, params={"limit": 2, "cursor": first["next_cursor"]})
    ).json()

    older = [item["scheduled_at"] for item in first["items"] + second["items"]]
    assert len(set(older)) == 4
    assert second["next_cursor"] is None


async def test_forged_cursor_is_422_without_echoing_it(client, monitor):
    url, _ = checks_url(monitor)

    response = await client.get(url, params={"cursor": "not-a-real-cursor!"})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_cursor"
    assert "not-a-real-cursor" not in response.text


async def test_a_cursor_never_reaches_another_monitor(client, session, monitor):
    # Cursors carry only a time: the monitor always comes from the URL.
    body = {"name": "Other", "url": "https://other.example", "interval_seconds": 60}
    other = (await client.post(MONITORS, json=body)).json()
    await add_check(session, monitor, ago=timedelta(minutes=1))
    far_future = encode_cursor(
        await session.scalar(select(func.now() + timedelta(days=1)))
    )

    response = await client.get(
        f"{MONITORS}/{other['id']}/checks", params={"cursor": far_future}
    )

    assert response.json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize("limit", [0, 101])
async def test_history_limit_is_bounded(client, monitor, limit):
    url, _ = checks_url(monitor)

    response = await client.get(url, params={"limit": limit})

    assert response.status_code == 422


# --- /stats ---


async def test_stats_of_a_healthy_monitor(client, session, monitor):
    for n, ms in enumerate([100, 200, 300, 400]):
        await add_check(session, monitor, ago=timedelta(minutes=n + 1), ms=ms)

    body = (await client.get(stats_url(monitor))).json()

    assert body["status"] == "up"
    assert body["period"] == "7d"
    assert {"from", "to"} <= body.keys() and "since" not in body
    assert body["uptime_percent"] == 100.0
    assert body["avg_response_time_ms"] == 250.0
    assert body["p95_response_time_ms"] == 385.0
    assert (body["checks_total"], body["checks_up"], body["checks_down"]) == (4, 4, 0)
    assert body["last_check"]["is_up"] is True


async def test_stats_count_down_checks_and_round_the_uptime(client, session, monitor):
    await add_check(session, monitor, ago=timedelta(minutes=1), is_up=False)
    await add_check(session, monitor, ago=timedelta(minutes=2))
    await add_check(session, monitor, ago=timedelta(minutes=3))

    body = (await client.get(stats_url(monitor))).json()

    assert body["status"] == "down"
    assert body["uptime_percent"] == 66.667
    assert (body["checks_up"], body["checks_down"]) == (2, 1)


async def test_stats_without_data_say_so(client, monitor):
    body = (await client.get(stats_url(monitor))).json()

    assert body["status"] == "unknown"
    assert body["last_check"] is None
    assert body["uptime_percent"] is None
    assert body["avg_response_time_ms"] is None
    assert body["checks_total"] == 0


async def test_stats_of_a_paused_monitor(client, session, monitor):
    await add_check(session, monitor, ago=timedelta(minutes=1))
    await client.patch(f"{MONITORS}/{monitor['id']}", json={"is_active": False})

    assert (await client.get(stats_url(monitor))).json()["status"] == "paused"


async def test_stale_last_check_is_unknown(client, session, monitor):
    # 60 s interval: a check from 10 minutes ago means the worker stopped.
    await add_check(session, monitor, ago=timedelta(minutes=10))

    body = (await client.get(stats_url(monitor))).json()

    assert body["status"] == "unknown"
    assert body["uptime_percent"] == 100.0  # the history is still the history


async def test_stats_period_limits_the_window(client, session, monitor):
    await add_check(session, monitor, ago=timedelta(hours=1))
    await add_check(session, monitor, ago=timedelta(days=3), is_up=False)

    day = (await client.get(stats_url(monitor), params={"period": "24h"})).json()
    week = (await client.get(stats_url(monitor), params={"period": "7d"})).json()

    assert (day["checks_total"], day["uptime_percent"]) == (1, 100.0)
    assert (week["checks_total"], week["uptime_percent"]) == (2, 50.0)


async def test_unknown_period_is_422(client, monitor):
    response = await client.get(stats_url(monitor), params={"period": "1y"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# --- both ---


@pytest.mark.parametrize("path", ["checks", "stats"])
async def test_unknown_monitor_is_404(client, path):
    response = await client.get(f"{MONITORS}/{UNKNOWN_ID}/{path}")

    assert response.status_code == 404
    assert response.json()["code"] == "monitor_not_found"


@pytest.mark.parametrize("path", ["checks", "stats"])
async def test_api_key_is_required(client, monitor, path):
    response = await client.get(
        f"{MONITORS}/{monitor['id']}/{path}", headers={"X-API-Key": ""}
    )

    assert response.status_code == 401


def test_api_error_kinds_match_the_database():
    assert get_args(ErrorKind) == ERROR_KINDS
