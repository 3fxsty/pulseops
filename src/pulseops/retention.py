"""Retention: checks older than 30 days are deleted (MVP business rule).

ArdiQ only wraps this (pulseops/queue/tasks.py), like pulseops.scheduling.
"""

import logging
import time
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pulseops.repositories.checks import delete_expired_checks

logger = logging.getLogger(__name__)

RETENTION = timedelta(days=30)
# Small batches keep every transaction, and its locks, short.
BATCH_SIZE = 5000
# No new batch starts after this; what is left goes in the next run.
MAX_RUN_SECONDS = 60.0


async def purge_expired_checks(
    sessions: async_sessionmaker[AsyncSession],
    *,
    retention: timedelta = RETENTION,
    batch_size: int = BATCH_SIZE,
    max_seconds: float = MAX_RUN_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Delete expired checks batch by batch, within a time budget.

    Each batch is its own short transaction, so a run cut short by the budget
    keeps what it already deleted. Returns how many checks were deleted.
    """
    deadline = clock() + max_seconds
    deleted = 0
    while True:
        async with sessions() as session:
            batch = await delete_expired_checks(
                session, retention=retention, batch_size=batch_size
            )
        deleted += batch
        if batch < batch_size:
            finished = True
            break
        if clock() >= deadline:
            finished = False
            break
    logger.info(
        "retention deleted=%s finished=%s%s",
        deleted,
        finished,
        "" if finished else " (time limit reached, the rest goes next run)",
    )
    return deleted
