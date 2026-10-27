from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select

from pulseops.config import get_settings
from pulseops.db.models import Check, Monitor
from pulseops.repositories import monitors as repository

pytestmark = pytest.mark.anyio

MONITORS = "/api/v1/monitors"


async def create(client, **overrides):
    body = {"name": "Example", "url": "https://example.com", "interval_seconds": 60}
    return await client.post(MONITORS, json=body | overrides)


# --- create ---


async def test_create_returns_201_with_location(client):
    response = await create(client, url="HTTPS://Example.com:443#top")

    assert response.status_code == 201
    body = response.json()
    assert body["url"] == "https://example.com/"
    assert body["is_active"] is True
    assert response.headers["location"] == f"{MONITORS}/{body['id']}"


async def test_create_stores_the_normalized_url(client, session):
    await create(client, url="https://Example.com./status#x")

    stored = await session.scalar(select(Monitor.url))
    assert stored == "https://example.com/status"


async def test_disguised_duplicate_url_is_a_conflict(client):
    await create(client, url="https://example.com/")

    response = await create(client, url="  HTTPS://Example.COM.:443/#again ")

    assert response.status_code == 409
    assert response.json()["code"] == "monitor_url_conflict"


@pytest.mark.parametrize("interval", [29, 86401])
async def test_create_rejects_interval_out_of_range(client, interval):
    response = await create(client, interval_seconds=interval)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_create_rejects_unknown_fields(client):
    response = await create(client, id=str(uuid4()))

    assert response.status_code == 422


async def test_create_rejects_internal_target(client):
    response = await create(client, url="http://169.254.169.254/")

    assert response.status_code == 422
    assert response.json()["code"] == "url_target_not_allowed"


async def test_create_rejects_invalid_url(client):
    response = await create(client, url="ftp://example.com")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"][0]["loc"] == ["body", "url"]


async def test_create_rejects_overlong_url_input(client):
    response = await create(client, url="https://example.com/" + "a" * 2100)

    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["body", "url"]


async def test_allow_private_targets_accepts_internal_urls(app, client):
    settings = get_settings().model_copy(update={"allow_private_targets": True})
    app.dependency_overrides[get_settings] = lambda: settings

    response = await create(client, url="http://10.0.0.5:8080/health")

    assert response.status_code == 201


# --- list ---


async def test_list_paginates_in_creation_order(client):
    for n in range(3):
        await create(client, name=f"m{n}", url=f"https://example.com/{n}")

    first = (await client.get(MONITORS, params={"limit": 2})).json()
    second = (await client.get(MONITORS, params={"limit": 2, "offset": 2})).json()

    assert [m["name"] for m in first["items"]] == ["m0", "m1"]
    assert [m["name"] for m in second["items"]] == ["m2"]
    assert first["total"] == second["total"] == 3
    assert (first["limit"], first["offset"]) == (2, 0)


async def test_list_filters_by_is_active(client):
    await create(client, url="https://example.com/on")
    await create(client, url="https://example.com/off", is_active=False)

    page = (await client.get(MONITORS, params={"is_active": "false"})).json()

    assert [m["url"] for m in page["items"]] == ["https://example.com/off"]
    assert page["total"] == 1


@pytest.mark.parametrize("params", [{"limit": 101}, {"limit": 0}, {"offset": -1}])
async def test_list_rejects_bad_pagination(client, params):
    response = await client.get(MONITORS, params=params)

    assert response.status_code == 422


# --- get ---


async def test_get_returns_the_monitor(client):
    created = (await create(client)).json()

    response = await client.get(f"{MONITORS}/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_get_unknown_monitor_is_404(client):
    response = await client.get(f"{MONITORS}/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "monitor_not_found"


async def test_get_malformed_id_is_422(client):
    response = await client.get(f"{MONITORS}/not-a-uuid")

    assert response.status_code == 422


# --- update ---


async def test_patch_changes_only_the_fields_sent(client):
    created = (await create(client, name="Old")).json()

    response = await client.patch(f"{MONITORS}/{created['id']}", json={"name": "New"})

    body = response.json()
    assert response.status_code == 200
    assert body["name"] == "New"
    assert body["url"] == created["url"]
    assert body["updated_at"] > created["updated_at"]


async def test_pausing_does_not_touch_dns(client, monkeypatch):
    created = (await create(client)).json()

    async def dns_must_not_be_called(host):
        raise AssertionError("DNS lookup while pausing")

    monkeypatch.setattr("pulseops.security.ssrf.resolve_host", dns_must_not_be_called)
    response = await client.patch(
        f"{MONITORS}/{created['id']}", json={"is_active": False}
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_patch_url_goes_through_ssrf_check(client):
    created = (await create(client)).json()

    response = await client.patch(
        f"{MONITORS}/{created['id']}", json={"url": "http://127.0.0.1:5432/"}
    )
    unchanged = (await client.get(f"{MONITORS}/{created['id']}")).json()

    assert response.status_code == 422
    assert response.json()["code"] == "url_target_not_allowed"
    assert unchanged["url"] == created["url"]


async def test_patch_url_is_normalized(client):
    created = (await create(client)).json()

    response = await client.patch(
        f"{MONITORS}/{created['id']}", json={"url": "HTTPS://New.Example.com#x"}
    )

    assert response.json()["url"] == "https://new.example.com/"


async def test_patch_url_to_an_existing_one_is_a_conflict(client):
    await create(client, url="https://taken.example.com")
    created = (await create(client, url="https://mine.example.com")).json()

    response = await client.patch(
        f"{MONITORS}/{created['id']}", json={"url": "https://Taken.example.com/"}
    )

    assert response.status_code == 409


@pytest.mark.parametrize("field", ["name", "url", "interval_seconds", "is_active"])
async def test_patch_null_for_a_required_field_is_422(client, field):
    created = (await create(client)).json()

    response = await client.patch(f"{MONITORS}/{created['id']}", json={field: None})

    assert response.status_code == 422


async def test_patch_unknown_monitor_is_404(client):
    response = await client.patch(f"{MONITORS}/{uuid4()}", json={"name": "x"})

    assert response.status_code == 404


# --- delete ---


async def test_delete_removes_monitor_and_its_checks(client, session):
    created = (await create(client)).json()
    monitor_id = await session.scalar(select(Monitor.id))
    await session.execute(
        insert(Check).values(
            monitor_id=monitor_id,
            scheduled_at=datetime(2026, 1, 1, tzinfo=UTC),
            is_up=True,
        )
    )
    await session.commit()

    response = await client.delete(f"{MONITORS}/{created['id']}")

    assert response.status_code == 204
    assert (await client.get(f"{MONITORS}/{created['id']}")).status_code == 404
    assert await session.scalar(select(func.count()).select_from(Check)) == 0


async def test_delete_unknown_monitor_is_404(client):
    response = await client.delete(f"{MONITORS}/{uuid4()}")

    assert response.status_code == 404


# --- repository guard (ADR-030) ---


async def test_repository_refuses_unvalidated_urls(session):
    with pytest.raises(TypeError):
        await repository.create_monitor(
            session,
            name="Sneaky",
            url="http://127.0.0.1/",
            interval_seconds=60,
            is_active=True,
        )
