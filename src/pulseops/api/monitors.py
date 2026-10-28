"""Monitor endpoints. HTTP only: validation and persistence live elsewhere."""

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from pulseops.api.cursors import InvalidCursorError, decode_cursor, encode_cursor
from pulseops.api.deps import SessionDep, SettingsDep, require_api_key
from pulseops.api.errors import invalid_cursor, monitor_not_found
from pulseops.api.schemas import (
    CheckPage,
    CheckRead,
    MonitorCreate,
    MonitorPage,
    MonitorRead,
    MonitorStats,
    MonitorUpdate,
    Period,
    Problem,
)
from pulseops.db.models import Monitor
from pulseops.repositories import checks as checks_repository
from pulseops.repositories import monitors as repository
from pulseops.security.validation import validate_monitor_url
from pulseops.status import current_status

PROBLEM = {"model": Problem, "content": {"application/problem+json": {}}}

router = APIRouter(
    prefix="/api/v1/monitors",
    tags=["monitors"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM, 422: PROBLEM},
)

# A closed list (never user-built SQL): windows ending now; nothing older
# than 30 days exists anyway (retention).
PERIODS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

# The API calls it `id`; in the code it is always the public_id (ADR-019).
PublicId = Annotated[UUID, Path(alias="id", description="Public monitor id.")]


async def get_monitor_or_404(session: SessionDep, public_id: PublicId) -> Monitor:
    monitor = await repository.get_monitor(session, public_id)
    if monitor is None:
        raise monitor_not_found()
    return monitor


MonitorDep = Annotated[Monitor, Depends(get_monitor_or_404)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={409: PROBLEM},
    summary="Create a monitor",
)
async def create_monitor(
    body: MonitorCreate,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> MonitorRead:
    url = await validate_monitor_url(
        body.url, allow_private_targets=settings.allow_private_targets
    )
    monitor = await repository.create_monitor(
        session,
        name=body.name,
        url=url,
        interval_seconds=body.interval_seconds,
        is_active=body.is_active,
    )
    response.headers["Location"] = request.app.url_path_for(
        "get_monitor", id=str(monitor.public_id)
    )
    return MonitorRead.from_model(monitor)


@router.get("", summary="List monitors")
async def list_monitors(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    is_active: bool | None = None,
) -> MonitorPage:
    items, total = await repository.list_monitors(
        session, limit=limit, offset=offset, is_active=is_active
    )
    return MonitorPage(
        items=[MonitorRead.from_model(monitor) for monitor in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{id}", responses={404: PROBLEM}, summary="Get a monitor")
async def get_monitor(monitor: MonitorDep) -> MonitorRead:
    return MonitorRead.from_model(monitor)


@router.patch(
    "/{id}",
    responses={404: PROBLEM, 409: PROBLEM},
    summary="Update a monitor (only the fields sent)",
)
async def update_monitor(
    body: MonitorUpdate,
    monitor: MonitorDep,
    session: SessionDep,
    settings: SettingsDep,
) -> MonitorRead:
    changes = body.model_dump(exclude_unset=True)
    # Without a new URL there is no URL check and no DNS lookup, so pausing
    # works even when the site's DNS is down.
    if "url" in changes:
        changes["url"] = await validate_monitor_url(
            changes["url"], allow_private_targets=settings.allow_private_targets
        )
    monitor = await repository.update_monitor(session, monitor, changes)
    return MonitorRead.from_model(monitor)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: PROBLEM},
    summary="Delete a monitor and its check history",
)
async def delete_monitor(monitor: MonitorDep, session: SessionDep) -> None:
    await repository.delete_monitor(session, monitor)


@router.get(
    "/{id}/checks",
    responses={404: PROBLEM},
    summary="List a monitor's checks, newest first",
)
async def list_monitor_checks(
    monitor: MonitorDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[
        str | None, Query(description="The `next_cursor` of the previous page.")
    ] = None,
) -> CheckPage:
    try:
        before = decode_cursor(cursor) if cursor is not None else None
    except InvalidCursorError:
        raise invalid_cursor() from None
    # One extra row says whether there is a next page.
    checks = await checks_repository.list_checks(
        session, monitor_id=monitor.id, limit=limit + 1, before=before
    )
    page, more = checks[:limit], len(checks) > limit
    return CheckPage(
        items=[CheckRead.from_model(check) for check in page],
        next_cursor=encode_cursor(page[-1].scheduled_at) if more else None,
    )


@router.get(
    "/{id}/stats",
    responses={404: PROBLEM},
    summary="Current status, uptime and response times over a period",
)
async def get_monitor_stats(
    monitor: MonitorDep,
    session: SessionDep,
    period: Period = "7d",
) -> MonitorStats:
    last = await checks_repository.latest_check(session, monitor.id)
    stats = await checks_repository.check_stats(
        session, monitor_id=monitor.id, period=PERIODS[period]
    )
    return MonitorStats(
        status=current_status(
            is_active=monitor.is_active,
            interval_seconds=monitor.interval_seconds,
            last_check_at=last.scheduled_at if last else None,
            last_check_up=last.is_up if last else None,
            now=stats.until,
        ),
        last_check=CheckRead.from_model(last) if last else None,
        period=period,
        since=stats.since,
        to=stats.until,
        # "No data" is neither 0 % nor 100 %.
        uptime_percent=round(stats.up / stats.total * 100, 3) if stats.total else None,
        avg_response_time_ms=_round_ms(stats.avg_response_time_ms),
        p95_response_time_ms=_round_ms(stats.p95_response_time_ms),
        checks_total=stats.total,
        checks_up=stats.up,
        checks_down=stats.total - stats.up,
    )


def _round_ms(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
