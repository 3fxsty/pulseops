"""Request and response bodies. Input and output are separate models, so a
client can never set server-owned fields, and never sees the internal id."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pulseops.db.models import Check, Incident, Monitor
from pulseops.status import Status

NAME_MAX_LENGTH = 100
# Raw input bound, equal to Pydantic HttpUrl's own limit so an overlong URL
# gets a clear error. The stored URL must fit 2048 once normalized (ADR-022).
URL_INPUT_MAX_LENGTH = 2083
INTERVAL_MIN_SECONDS = 30
INTERVAL_MAX_SECONDS = 86400


class MonitorCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "name": "Example site",
                    "url": "https://example.com",
                    "interval_seconds": 60,
                }
            ]
        },
    )

    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    url: str = Field(
        max_length=URL_INPUT_MAX_LENGTH,
        description="http or https URL. Stored normalized; credentials are refused.",
    )
    interval_seconds: int = Field(ge=INTERVAL_MIN_SECONDS, le=INTERVAL_MAX_SECONDS)
    is_active: bool = True


class MonitorUpdate(BaseModel):
    """Partial update: only the fields sent change. None of them accepts null."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={"examples": [{"is_active": False}]},
    )

    name: str = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH)
    url: str = Field(default=None, max_length=URL_INPUT_MAX_LENGTH)
    interval_seconds: int = Field(
        default=None, ge=INTERVAL_MIN_SECONDS, le=INTERVAL_MAX_SECONDS
    )
    is_active: bool = Field(default=None)


class MonitorRead(BaseModel):
    id: UUID = Field(description="Public identifier of the monitor.")
    name: str
    url: str
    interval_seconds: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, monitor: Monitor) -> Self:
        # Mapped field by field: the internal integer id is never exposed.
        return cls(
            id=monitor.public_id,
            name=monitor.name,
            url=monitor.url,
            interval_seconds=monitor.interval_seconds,
            is_active=monitor.is_active,
            created_at=monitor.created_at,
            updated_at=monitor.updated_at,
        )


class MonitorPage(BaseModel):
    items: list[MonitorRead]
    total: int
    limit: int
    offset: int


ErrorKind = Literal[
    "timeout",
    "dns_error",
    "connection_error",
    "ssl_error",
    "http_error",
    "blocked_target",
]
Period = Literal["24h", "7d", "30d"]
Resolution = Literal["recovered", "paused", "monitor_changed"]
IncidentState = Literal["open", "resolved"]


class CheckRead(BaseModel):
    scheduled_at: datetime = Field(description="When the check was due.")
    is_up: bool
    status_code: int | None
    response_time_ms: int | None
    error_kind: ErrorKind | None
    error_detail: str | None

    @classmethod
    def from_model(cls, check: Check) -> Self:
        return cls(
            scheduled_at=check.scheduled_at,
            is_up=check.is_up,
            status_code=check.status_code,
            response_time_ms=check.response_time_ms,
            error_kind=check.error_kind,
            error_detail=check.error_detail,
        )


class CheckPage(BaseModel):
    items: list[CheckRead]
    next_cursor: str | None = Field(
        description="Pass it as `cursor` to get the next page; null on the last one."
    )


class IncidentRead(BaseModel):
    """An outage: consecutive failed checks, from start to end (ADR-060)."""

    id: UUID = Field(description="Public identifier of the incident.")
    started_at: datetime = Field(description="When its first failed check was due.")
    resolved_at: datetime | None = Field(
        description="When its first successful check was due, or when the "
        "monitor was paused or got a new URL. Null while open."
    )
    error_kind: ErrorKind = Field(description="Why its first failed check failed.")
    status_code: int | None
    resolution: Resolution | None = Field(description="How it ended. Null while open.")

    @classmethod
    def from_model(cls, incident: Incident) -> Self:
        # Mapped field by field: the internal integer ids are never exposed.
        return cls(
            id=incident.public_id,
            started_at=incident.started_at,
            resolved_at=incident.resolved_at,
            error_kind=incident.error_kind,
            status_code=incident.status_code,
            resolution=incident.resolution,
        )


class IncidentPage(BaseModel):
    items: list[IncidentRead]
    next_cursor: str | None = Field(
        description="Pass it as `cursor` to get the next page; null on the last one."
    )


class MonitorRef(BaseModel):
    id: UUID = Field(description="Public identifier of the monitor.")
    name: str


class IncidentAcrossMonitors(BaseModel):
    """An incident in the list across monitors: which monitor it belongs to."""

    id: UUID
    monitor: MonitorRef
    started_at: datetime
    resolved_at: datetime | None
    error_kind: ErrorKind
    status_code: int | None
    resolution: Resolution | None

    @classmethod
    def from_row(cls, incident: Incident, monitor_id: UUID, monitor_name: str) -> Self:
        return cls(
            **IncidentRead.from_model(incident).model_dump(),
            monitor=MonitorRef(id=monitor_id, name=monitor_name),
        )


class IncidentAcrossMonitorsPage(BaseModel):
    items: list[IncidentAcrossMonitors]
    next_cursor: str | None = Field(
        description="Pass it as `cursor` to get the next page; null on the last one."
    )


class OpenIncidentRead(BaseModel):
    id: UUID
    started_at: datetime
    error_kind: ErrorKind
    status_code: int | None

    @classmethod
    def from_model(cls, incident: Incident) -> Self:
        return cls(
            id=incident.public_id,
            started_at=incident.started_at,
            error_kind=incident.error_kind,
            status_code=incident.status_code,
        )


class MonitorStats(BaseModel):
    status: Status = Field(
        description="From the latest check; `unknown` if there is none or it is "
        "older than 2 intervals + 60 s, `paused` if the monitor is inactive."
    )
    last_check: CheckRead | None
    open_incident: OpenIncidentRead | None = Field(
        description="The monitor's incident still going on, if any."
    )
    period: Period
    # `from` is a Python keyword: the field is renamed only on the wire.
    since: datetime = Field(serialization_alias="from")
    to: datetime
    uptime_percent: float | None = Field(
        description="Checks up / checks in the period x 100. Null without data."
    )
    avg_response_time_ms: float | None = Field(
        description="Mean over the checks that were up."
    )
    p95_response_time_ms: float | None = Field(
        description="95th percentile over the checks that were up."
    )
    checks_total: int
    checks_up: int
    checks_down: int


class ValidationErrorItem(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class Problem(BaseModel):
    """RFC 9457 Problem Details, plus a stable machine-readable `code`."""

    type: str = Field(examples=["/problems/monitor-not-found"])
    title: str
    status: int
    detail: str
    code: str = Field(examples=["monitor_not_found"])
    errors: list[ValidationErrorItem] | None = None
