"""add incidents and notifications

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-03 19:37:23.862661

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # New, empty tables: no existing data is touched. pulseops_app gets its
    # row privileges on them through the owner's default privileges.
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "public_id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False
        ),
        sa.Column("monitor_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_kind", sa.String(length=32), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("resolution", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "error_kind IN ('timeout', 'dns_error', 'connection_error', "
            "'ssl_error', 'http_error', 'blocked_target')",
            name=op.f("ck_incidents_error_kind_valid"),
        ),
        sa.CheckConstraint(
            "resolution IN ('recovered', 'paused', 'monitor_changed')",
            name=op.f("ck_incidents_resolution_valid"),
        ),
        sa.CheckConstraint(
            "(resolved_at IS NULL) = (resolution IS NULL)",
            name=op.f("ck_incidents_resolved_at_matches_resolution"),
        ),
        sa.CheckConstraint(
            "resolved_at >= started_at",
            name=op.f("ck_incidents_resolved_after_started"),
        ),
        sa.CheckConstraint(
            "status_code BETWEEN 100 AND 599",
            name=op.f("ck_incidents_status_code_range"),
        ),
        sa.ForeignKeyConstraint(
            ["monitor_id"],
            ["monitors.id"],
            name=op.f("fk_incidents_monitor_id_monitors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
        sa.UniqueConstraint(
            "monitor_id", "started_at", name=op.f("uq_incidents_monitor_id_started_at")
        ),
        sa.UniqueConstraint("public_id", name=op.f("uq_incidents_public_id")),
    )
    op.create_index(
        "ix_incidents_monitor_id_open",
        "incidents",
        ["monitor_id"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index(
        "ix_incidents_started_at_public_id",
        "incidents",
        ["started_at", "public_id"],
        unique=False,
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("first_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'pending') = (finished_at IS NULL)",
            name=op.f("ck_notifications_finished_at_matches_status"),
        ),
        sa.CheckConstraint(
            "kind IN ('opened', 'resolved')", name=op.f("ck_notifications_kind_valid")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')",
            name=op.f("ck_notifications_status_valid"),
        ),
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_notifications_attempts_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_notifications_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint(
            "incident_id", "kind", name=op.f("uq_notifications_incident_id_kind")
        ),
    )
    op.create_index(
        "ix_notifications_next_attempt_at_pending",
        "notifications",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Deletes every incident and alert (the checks stay).
    op.drop_index(
        "ix_notifications_next_attempt_at_pending",
        table_name="notifications",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("notifications")
    op.drop_index("ix_incidents_started_at_public_id", table_name="incidents")
    op.drop_index(
        "ix_incidents_monitor_id_open",
        table_name="incidents",
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.drop_table("incidents")
