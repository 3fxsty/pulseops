import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
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
# How an incident ended. Must match ck_incidents_resolution_valid.
INCIDENT_RESOLUTIONS = ("recovered", "paused", "monitor_changed")
# Must match ck_notifications_kind_valid and ck_notifications_status_valid.
NOTIFICATION_KINDS = ("opened", "resolved")
NOTIFICATION_STATUSES = ("pending", "sent", "failed", "skipped")


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
    incidents: Mapped[list["Incident"]] = relationship(
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


class SchedulerHeartbeat(Base):
    """A single row: when the scheduler last completed a tick.

    Written in the same transaction as each tick's claim, empty ticks
    included, so it only moves when scheduling really works. Lets the API
    (Phase 7, /health) tell a quiet PulseOps from a dead one without access
    to Valkey.
    """

    __tablename__ = "scheduler_heartbeat"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, autoincrement=False, server_default=text("1")
    )
    last_success_at: Mapped[datetime]


class Incident(Base):
    """An outage of a monitor: consecutive failed checks, from start to end.

    Opened and closed by pulseops/incidents.py (ADR-060), in the transaction
    that stores the check (ADR-061).
    """

    __tablename__ = "incidents"
    __table_args__ = (
        # A monitor never has two incidents starting at the same check. Also
        # the index for one monitor's incident history.
        UniqueConstraint("monitor_id", "started_at"),
        CheckConstraint(
            "error_kind IN ('timeout', 'dns_error', 'connection_error', "
            "'ssl_error', 'http_error', 'blocked_target')",
            name="error_kind_valid",
        ),
        CheckConstraint("status_code BETWEEN 100 AND 599", name="status_code_range"),
        CheckConstraint(
            "resolution IN ('recovered', 'paused', 'monitor_changed')",
            name="resolution_valid",
        ),
        CheckConstraint(
            "(resolved_at IS NULL) = (resolution IS NULL)",
            name="resolved_at_matches_resolution",
        ),
        CheckConstraint("resolved_at >= started_at", name="resolved_after_started"),
        # At most one open incident per monitor, whatever the code does.
        Index(
            "ix_incidents_monitor_id_open",
            "monitor_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
        # Incidents across monitors, newest first (ADR-069).
        Index("ix_incidents_started_at_public_id", "started_at", "public_id"),
    )
    __mapper_args__ = {"eager_defaults": True}

    # Internal key; never exposed by the API.
    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        unique=True, server_default=func.uuidv7()
    )
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE")
    )
    # scheduled_at of the first failed check of the streak.
    started_at: Mapped[datetime]
    # scheduled_at of the first successful check, or the time of the pause or
    # URL change that closed it. None while the incident is open.
    resolved_at: Mapped[datetime | None]
    # Why the first failed check failed (alerts carry it, checks expire).
    error_kind: Mapped[str] = mapped_column(String(32))
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    resolution: Mapped[str | None] = mapped_column(String(32))

    monitor: Mapped[Monitor] = relationship(back_populates="incidents")
    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="incident",
        cascade="all, delete",
        passive_deletes=True,
    )


class Notification(Base):
    """An alert waiting to be sent, or already handled (the outbox, ADR-063).

    Written in the same transaction as its incident; delivered later by the
    worker's deliver_notifications cron.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # One alert of each kind per incident.
        UniqueConstraint("incident_id", "kind"),
        CheckConstraint("kind IN ('opened', 'resolved')", name="kind_valid"),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')", name="status_valid"
        ),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        # Pending alerts are not finished; every other status is.
        CheckConstraint(
            "(status = 'pending') = (finished_at IS NULL)",
            name="finished_at_matches_status",
        ),
        # The delivery cron asks "which pending alerts are due?" every 5 s.
        Index(
            "ix_notifications_next_attempt_at_pending",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # When it may be tried next. A claim pushes it 60 s ahead (a lease).
    next_attempt_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # When it was first tried: retries stop 24 h after it (ADR-063). Counted
    # from here, not from created_at, so an alert that waited (e.g. with the
    # worker stopped) still gets its full day of retries.
    first_attempt_at: Mapped[datetime | None]
    # When it became sent, failed or skipped.
    finished_at: Mapped[datetime | None]

    incident: Mapped[Incident] = relationship(back_populates="notifications")
