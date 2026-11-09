import asyncio
import time
from datetime import timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pulseops.api import health
from pulseops.api.deps import get_session
from pulseops.db.models import SchedulerHeartbeat
from pulseops.main import app

pytestmark = pytest.mark.anyio

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- /health/scheduler (ADR-068) ---


@pytest.fixture
async def anonymous(app):
    """A client without the API key, as an outside monitor would call."""
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def last_tick(session, seconds_ago: int) -> None:
    session.add(
        SchedulerHeartbeat(last_success_at=func.now() - timedelta(seconds=seconds_ago))
    )
    await session.commit()


def assert_answer(response, code: int, status: str) -> None:
    assert response.status_code == code
    # Exactly this: no timestamp, no error detail.
    assert response.json() == {"status": status}
    # Requested by the project owner: never an old "ok" from a cache.
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("seconds_ago", "code", "status"),
    [(5, 200, "ok"), (59, 200, "ok"), (61, 503, "stale")],
)
async def test_the_answer_follows_the_last_tick(
    anonymous, session, seconds_ago, code, status
):
    await last_tick(session, seconds_ago)

    assert_answer(await anonymous.get("/health/scheduler"), code, status)


async def test_a_scheduler_that_never_ran_is_stale(anonymous):
    assert_answer(await anonymous.get("/health/scheduler"), 503, "stale")


async def test_an_unreachable_database_is_unavailable(app, anonymous, monkeypatch):
    # Nothing listens on port 1. Depending on the machine, the connection is
    # refused at once or hangs until asyncpg's 60 s connect timeout: either
    # way the probe answers within its deadline (shortened here).
    monkeypatch.setattr(health, "DATABASE_DEADLINE_SECONDS", 0.5)
    engine = create_async_engine("postgresql+asyncpg://nobody:nothing@127.0.0.1:1/x")

    async def unreachable():
        async with async_sessionmaker(engine)() as session:
            yield session

    app.dependency_overrides[get_session] = unreachable
    try:
        assert_answer(await anonymous.get("/health/scheduler"), 503, "unavailable")
    finally:
        await engine.dispose()


async def test_a_database_that_hangs_is_cut_at_the_deadline(anonymous, monkeypatch):
    async def hang(session, window):
        await asyncio.sleep(30)

    monkeypatch.setattr(health, "scheduler_ran_within", hang)
    monkeypatch.setattr(health, "DATABASE_DEADLINE_SECONDS", 0.2)
    started = time.perf_counter()

    assert_answer(await anonymous.get("/health/scheduler"), 503, "unavailable")
    assert time.perf_counter() - started < 1
