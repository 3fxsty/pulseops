"""PostgreSQL server settings PulseOps relies on (set in docker-compose.yml)."""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.anyio


async def test_error_log_leaves_out_row_values(app_engine):
    # Otherwise a duplicate monitor URL logs "DETAIL: Key (url)=(<the URL>)
    # already exists", and a CHECK violation the whole row. URLs may carry
    # tokens (ADR-044).
    async with app_engine.connect() as connection:
        verbosity = await connection.scalar(text("SHOW log_error_verbosity"))

    assert verbosity == "terse"
