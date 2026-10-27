import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    String,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pulseops.db.base import Base

# Why a check failed. Must match the ck_checks_error_kind_valid constraint.
ERROR_KINDS = (
    "timeout",
    "dns_error",
    "connection_error",
    "ssl_error",
    "http_error",
    "blocked_target",
)


class Monitor(Base):
    """A website or API to check periodically."""

    __tablename__ = "monitors"
    __table_args__ = (
        CheckConstraint(
            "interval_seconds BETWEEN 30 AND 86400",
            name="interval_seconds_range",
        ),
        # The scheduler asks "which active monitors are due?" every few
        # seconds; inactive ones are left out of the index entirely.
        Index(
            "ix_monitors_next_check_at_active",
            "next_check_at",
            postgresql_where=text("is_active"),
        ),
    )
    # Fetch server-generated values (public_id, timestamps) with RETURNING on
    # INSERT and UPDATE, instead of a second query.
    __mapper_args__ = {"eager_defaults": True}

    # Internal key, used for joins; never exposed by the API.
    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    # Stable, opaque identifier for API URLs.
    public_id: Mapped[uuid.UUID] = mapped_column(
        unique=True, server_default=func.uuidv7()
    )
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    interval_seconds: Mapped[int]
    is_active: Mapped[bool] = mapped_column(server_default=true())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    # When the next check is due. The schedule lives here, in PostgreSQL, not
    # in the queue: losing Valkey costs at most one check per monitor.
    next_check_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # PostgreSQL deletes the checks (ON DELETE CASCADE); passive_deletes stops
    # the ORM from loading them all into memory first.
    checks: Mapped[list["Check"]] = relationship(
        back_populates="monitor",
        cascade="all, delete",
        passive_deletes=True,
    )


class Check(Base):
    """The outcome of one scheduled check of a monitor."""

    __tablename__ = "checks"
    __table_args__ = (
        CheckConstraint("status_code BETWEEN 100 AND 599", name="status_code_range"),
        CheckConstraint("response_time_ms >= 0", name="response_time_ms_non_negative"),
        CheckConstraint(
            "error_kind IN ('timeout', 'dns_error', 'connection_error', "
            "'ssl_error', 'http_error', 'blocked_target')",
            name="error_kind_valid",
        ),
        CheckConstraint(
            "is_up = (error_kind IS NULL)", name="is_up_matches_error_kind"
        ),
        # The 30-day retention cleanup deletes by date across all monitors.
        Index("ix_checks_scheduled_at_brin", "scheduled_at", postgresql_using="brin"),
    )

    # The composite primary key makes a re-delivered check a no-op
    # (INSERT ... ON CONFLICT DO NOTHING) and covers per-monitor history.
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"), primary_key=True
    )
    # When the check was due, not when it actually ran.
    scheduled_at: Mapped[datetime] = mapped_column(primary_key=True)
    is_up: Mapped[bool]
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    response_time_ms: Mapped[int | None]
    error_kind: Mapped[str | None] = mapped_column(String(32))
    error_detail: Mapped[str | None] = mapped_column(String(500))

    monitor: Mapped[Monitor] = relationship(back_populates="checks")
