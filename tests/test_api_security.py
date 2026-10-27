"""Things that must never happen (N5)."""

import logging

import httpx2
import pytest
from pydantic import ValidationError

from pulseops.config import ApiSettings, Settings
from pulseops.main import create_app
from pulseops.repositories import monitors as repository

pytestmark = pytest.mark.anyio

MONITORS = "/api/v1/monitors"
MONITOR_FIELDS = {
    "id",
    "name",
    "url",
    "interval_seconds",
    "is_active",
    "created_at",
    "updated_at",
}
INTERNAL_MARKERS = ["uq_monitors", "ck_monitors", "INSERT", "SELECT", "Traceback"]


async def create(client, **overrides):
    body = {"name": "Example", "url": "https://example.com", "interval_seconds": 60}
    return await client.post(MONITORS, json=body | overrides)


def assert_no_internals(response):
    for marker in INTERNAL_MARKERS:
        assert marker not in response.text


async def test_monitor_responses_have_exactly_the_public_fields(client):
    created = (await create(client)).json()
    listed = (await client.get(MONITORS)).json()["items"][0]

    assert set(created) == MONITOR_FIELDS
    assert set(listed) == MONITOR_FIELDS


async def test_errors_are_problem_details(client):
    response = await client.get(f"{MONITORS}/not-a-uuid")

    assert response.headers["content-type"] == "application/problem+json"
    assert {"type", "title", "status", "detail", "code"} <= set(response.json())


async def test_errors_never_leak_database_internals(client):
    await create(client)
    conflict = await create(client)
    invalid = await create(client, interval_seconds=5)

    assert conflict.status_code == 409
    assert_no_internals(conflict)
    assert_no_internals(invalid)


async def test_validation_errors_never_echo_input(client):
    response = await create(client, name="x" * 101, interval_seconds="secret-value")

    assert response.status_code == 422
    assert all(
        set(error) == {"loc", "msg", "type"} for error in response.json()["errors"]
    )
    assert "secret-value" not in response.text


async def test_password_in_url_is_never_echoed(client):
    response = await create(client, url="https://usuario:secreto@example.com/")

    assert response.status_code == 422
    assert response.json()["code"] == "url_credentials_not_allowed"
    assert "secreto" not in response.text


async def test_unexpected_error_is_a_generic_500(app, api_key, fake_dns, monkeypatch):
    async def explode(*args, **kwargs):
        raise RuntimeError("boom: secret internal detail")

    monkeypatch.setattr(repository, "list_monitors", explode)
    transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx2.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as client:
        response = await client.get(MONITORS)

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "boom" not in response.text
    assert_no_internals(response)


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
async def test_missing_or_wrong_api_key_is_401(client, headers):
    client.headers.pop("X-API-Key")

    response = await client.get(MONITORS, headers=headers)

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


async def test_health_needs_no_api_key(client):
    client.headers.pop("X-API-Key")

    assert (await client.get("/health")).status_code == 200


async def test_api_key_never_reaches_the_logs(client, api_key, caplog):
    caplog.set_level(logging.DEBUG)

    await create(client)
    await client.get(MONITORS, headers={"X-API-Key": api_key + "x"})

    assert api_key not in caplog.text


def test_short_api_key_refuses_to_start_without_leaking_it():
    short_key = "too-short-but-secret"

    with pytest.raises(ValidationError) as error:
        ApiSettings(api_key=short_key)

    assert short_key not in str(error.value)


def test_api_settings_never_carry_the_broker_password():
    # The API does not use the queue; only BrokerSettings (worker) has it.
    assert "broker_url" not in Settings.model_fields
    assert "broker_url" not in ApiSettings.model_fields


async def test_docs_can_be_disabled(api_key):
    app = create_app(ApiSettings(api_key=api_key, docs_enabled=False))
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as c:
        for path in ["/docs", "/redoc", "/openapi.json"]:
            assert (await c.get(path)).status_code == 404


async def test_docs_are_served_when_enabled(client):
    assert (await client.get("/openapi.json")).status_code == 200


async def test_no_cors_headers(client):
    response = await client.options(
        MONITORS,
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers
