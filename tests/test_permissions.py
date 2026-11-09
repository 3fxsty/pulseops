"""The app role (pulseops_app) works with rows but can never change the schema."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

pytestmark = pytest.mark.anyio

INSUFFICIENT_PRIVILEGE = "42501"


async def test_app_role_can_read_and_write_rows(app_engine):
    async with app_engine.begin() as connection:
        monitor_id = await connection.scalar(
            text(
                "INSERT INTO monitors (name, url, interval_seconds) "
                "VALUES ('Example', 'https://example.com', 60) RETURNING id"
            )
        )
        await connection.execute(
            text("UPDATE monitors SET name = 'Renamed' WHERE id = :id"),
            {"id": monitor_id},
        )
        name = await connection.scalar(
            text("SELECT name FROM monitors WHERE id = :id"), {"id": monitor_id}
        )
        deleted = await connection.execute(
            text("DELETE FROM monitors WHERE id = :id"), {"id": monitor_id}
        )

    assert name == "Renamed"
    assert deleted.rowcount == 1


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE intruder (id integer)",
        "ALTER TABLE monitors ADD COLUMN intruder integer",
        "DROP TABLE checks",
    ],
    ids=["create", "alter", "drop"],
)
async def test_app_role_cannot_change_schema(app_engine, statement):
    async with app_engine.connect() as connection:
        with pytest.raises(ProgrammingError) as error:
            await connection.execute(text(statement))

    assert error.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


async def test_app_role_can_write_incidents_and_notifications(app_engine):
    # The tables were created by migration 0004 as pulseops_owner; the app role
    # gets its row privileges from the owner's default privileges.
    async with app_engine.begin() as connection:
        monitor_id = await connection.scalar(
            text(
                "INSERT INTO monitors (name, url, interval_seconds) "
                "VALUES ('Example', 'https://example.com', 60) RETURNING id"
            )
        )
        incident_id = await connection.scalar(
            text(
                "INSERT INTO incidents (monitor_id, started_at, error_kind) "
                "VALUES (:monitor_id, now(), 'timeout') RETURNING id"
            ),
            {"monitor_id": monitor_id},
        )
        await connection.execute(
            text(
                "INSERT INTO notifications (incident_id, kind) "
                "VALUES (:incident_id, 'opened')"
            ),
            {"incident_id": incident_id},
        )
        await connection.execute(
            text("UPDATE notifications SET attempts = 1 WHERE incident_id = :id"),
            {"id": incident_id},
        )
        deleted = await connection.execute(
            text("DELETE FROM incidents WHERE id = :id"), {"id": incident_id}
        )

    assert deleted.rowcount == 1


async def test_app_role_can_take_transaction_advisory_locks(app_engine):
    # Incident evaluation serialises checks of one monitor with this (ADR-061).
    async with app_engine.begin() as connection:
        await connection.execute(text("SELECT pg_advisory_xact_lock(1, 2)"))
        held = await connection.scalar(
            text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                "AND pid = pg_backend_pid()"
            )
        )

    assert held == 1
