"""Monitor endpoints. HTTP only: validation and persistence live elsewhere."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from pulseops.api.deps import SessionDep, SettingsDep, require_api_key
from pulseops.api.errors import monitor_not_found
from pulseops.api.schemas import (
    MonitorCreate,
    MonitorPage,
    MonitorRead,
    MonitorUpdate,
    Problem,
)
from pulseops.db.models import Monitor
from pulseops.repositories import monitors as repository
from pulseops.security.validation import validate_monitor_url

PROBLEM = {"model": Problem, "content": {"application/problem+json": {}}}

router = APIRouter(
    prefix="/api/v1/monitors",
    tags=["monitors"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM, 422: PROBLEM},
)

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
