"""Request and response bodies. Input and output are separate models, so a
client can never set server-owned fields, and never sees the internal id."""

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pulseops.db.models import Monitor

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
