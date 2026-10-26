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
