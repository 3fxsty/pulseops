"""Health probes, without the API key: for Docker and for outside monitors."""

import asyncio
import logging
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pulseops.api.deps import SessionDep
from pulseops.repositories.scheduling import scheduler_ran_within

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# The scheduler ticks every 5 s: a minute without a tick is 12 missed ones.
SCHEDULER_STALE_AFTER_SECONDS = 60
# Without it, an unreachable database could hold the probe for a minute.
DATABASE_DEADLINE_SECONDS = 3.0
# No proxy or cache may keep serving an old "ok" (requested by the project
# owner).
NO_STORE = {"Cache-Control": "no-store"}


class SchedulerHealth(BaseModel):
    status: Literal["ok", "stale", "unavailable"]


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe: answers as long as the API process is up."""
    return {"status": "ok"}


@router.get(
    "/health/scheduler",
    response_model=SchedulerHealth,
    responses={503: {"model": SchedulerHealth}},
)
async def scheduler_health(session: SessionDep) -> JSONResponse:
    """Whether the scheduler completed a tick in the last 60 s (ADR-068).

    200 `ok`; 503 `stale` (older, or it never ran) or `unavailable` (the
    database did not answer within 3 s). Plain JSON, never a timestamp.
    """
    try:
        async with asyncio.timeout(DATABASE_DEADLINE_SECONDS):
            fresh = await scheduler_ran_within(
                session, timedelta(seconds=SCHEDULER_STALE_AFTER_SECONDS)
            )
    except Exception as error:
        # A probe answers, whatever happened; the type is enough to look into
        # it, and the details stay out of the answer.
        logger.warning("scheduler health unavailable: %s", type(error).__name__)
        return _answer("unavailable", 503)
    return _answer("ok", 200) if fresh else _answer("stale", 503)


def _answer(status: str, code: int) -> JSONResponse:
    return JSONResponse({"status": status}, status_code=code, headers=NO_STORE)
