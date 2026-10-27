"""What PulseOps relies on from ArdiQ, verified against a real Valkey.

ardiq.testing.inline ignores delays and expiry, so these run a real worker on
a throwaway queue in the test logical database.
"""

import asyncio
import contextlib
import uuid

import pytest
from ardiq import Ardiq

pytestmark = pytest.mark.anyio


@pytest.fixture
async def queue(test_broker_url):
    """A throwaway queue with one task that records its runs."""
    app = Ardiq(redis_url=test_broker_url, queue_name=f"pulseops_test_{uuid.uuid4()}")
    runs: list[int] = []

    @app.task(name="probe")
    async def probe(n: int) -> None:
        runs.append(n)

    yield app, probe, runs
    await app._core.purge()


@contextlib.asynccontextmanager
async def running(app):
    worker = asyncio.create_task(app.run())
    try:
        yield
    finally:
        app.stop()
        await asyncio.wait_for(worker, 10)


async def wait_for_runs(runs, count, timeout=5.0):
    async with asyncio.timeout(timeout):
        while len(runs) < count:
            await asyncio.sleep(0.05)


async def test_same_task_id_while_waiting_runs_once(queue):
    # Two scheduler ticks enqueueing the same slot: one check.
    app, probe, runs = queue
    await probe.options(task_id="check:1:100").enqueue(1)
    await probe.options(task_id="check:1:100").enqueue(2)

    async with running(app):
        await wait_for_runs(runs, 1)
        await asyncio.sleep(0.3)

    assert runs == [1]


async def test_same_task_id_after_it_finished_runs_again(queue):
    # Dedup only lasts while the task exists: a slot re-enqueued after its
    # check finished is checked again, and ON CONFLICT DO NOTHING keeps the
    # first outcome. That is why both safeguards are needed.
    app, probe, runs = queue

    async with running(app):
        await probe.options(task_id="check:1:100").enqueue(1)
        await wait_for_runs(runs, 1)
        await probe.options(task_id="check:1:100").enqueue(2)
        await wait_for_runs(runs, 2)

    assert runs == [1, 2]


async def test_expired_tasks_are_dropped_without_running(queue):
    # A check not started before the monitor's next slot is useless.
    app, probe, runs = queue
    await probe.options(task_id="stale", expire_ms=100).enqueue(1)
    await probe.options(task_id="fresh", expire_ms=10_000).enqueue(2)
    await asyncio.sleep(0.3)

    async with running(app):
        await wait_for_runs(runs, 1)
        await asyncio.sleep(0.3)

    assert runs == [2]
    assert await app.status("stale") == "not_found"


async def test_payload_carries_plain_integers(queue):
    # msgpack: the check task gets (monitor_id, scheduled_at in µs) intact.
    app, probe, runs = queue
    microseconds = 1_793_140_694_931_815  # a 2026 timestamp, 16 digits

    async with running(app):
        await probe.enqueue(microseconds)
        await wait_for_runs(runs, 1)

    assert runs == [microseconds]
