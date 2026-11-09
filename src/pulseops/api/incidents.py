"""Incident endpoints (ADR-069). HTTP only: the queries live in the repository."""

from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from pulseops.api.cursors import (
    InvalidCursorError,
    decode_incident_cursor,
    encode_incident_cursor,
)
from pulseops.api.deps import SessionDep, require_api_key
from pulseops.api.errors import invalid_cursor
from pulseops.api.schemas import (
    IncidentAcrossMonitors,
    IncidentAcrossMonitorsPage,
    IncidentState,
    Problem,
)
from pulseops.repositories import incidents as repository

PROBLEM = {"model": Problem, "content": {"application/problem+json": {}}}

router = APIRouter(
    prefix="/api/v1/incidents",
    tags=["incidents"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM, 422: PROBLEM},
)

Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[
    str | None, Query(description="The `next_cursor` of the previous page.")
]


async def incident_page(
    session: AsyncSession, *, limit: int, cursor: str | None, **filters
) -> tuple[Sequence[Row], str | None]:
    """One page of (incident, monitor id, monitor name) rows, and the cursor
    of the next page (None on the last one)."""
    try:
        before = decode_incident_cursor(cursor) if cursor is not None else None
    except InvalidCursorError:
        raise invalid_cursor() from None
    # One extra row says whether there is a next page.
    rows = await repository.list_incidents(
        session, limit=limit + 1, before=before, **filters
    )
    page, more = rows[:limit], len(rows) > limit
    last = page[-1].Incident if more else None
    return page, encode_incident_cursor(
        last.started_at, last.public_id
    ) if last else None


@router.get("", summary="List incidents across monitors, newest first")
async def list_incidents(
    session: SessionDep,
    state: IncidentState | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
) -> IncidentAcrossMonitorsPage:
    page, next_cursor = await incident_page(
        session, limit=limit, cursor=cursor, state=state
    )
    return IncidentAcrossMonitorsPage(
        items=[IncidentAcrossMonitors.from_row(*row) for row in page],
        next_cursor=next_cursor,
    )
