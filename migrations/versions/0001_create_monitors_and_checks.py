"""create monitors and checks

Revision ID: 0001
Revises:
Create Date: 2026-10-26 23:18:46.606765

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "monitors",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "public_id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "interval_seconds BETWEEN 30 AND 86400",
            name=op.f("ck_monitors_interval_seconds_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monitors")),
        sa.UniqueConstraint("public_id", name=op.f("uq_monitors_public_id")),
        sa.UniqueConstraint("url", name=op.f("uq_monitors_url")),
    )
    op.create_table(
        "checks",
        sa.Column("monitor_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_up", sa.Boolean(), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("error_kind", sa.String(length=32), nullable=True),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "error_kind IN ('timeout', 'dns_error', 'connection_error', "
            "'ssl_error', 'http_error', 'blocked_target')",
            name=op.f("ck_checks_error_kind_valid"),
        ),
        sa.CheckConstraint(
            "is_up = (error_kind IS NULL)",
            name=op.f("ck_checks_is_up_matches_error_kind"),
        ),
        sa.CheckConstraint(
            "response_time_ms >= 0",
            name=op.f("ck_checks_response_time_ms_non_negative"),
        ),
        sa.CheckConstraint(
            "status_code BETWEEN 100 AND 599", name=op.f("ck_checks_status_code_range")
        ),
        sa.ForeignKeyConstraint(
            ["monitor_id"],
            ["monitors.id"],
            name=op.f("fk_checks_monitor_id_monitors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("monitor_id", "scheduled_at", name=op.f("pk_checks")),
    )
    op.create_index(
        "ix_checks_scheduled_at_brin",
        "checks",
        ["scheduled_at"],
        unique=False,
        postgresql_using="brin",
    )


def downgrade() -> None:
    """Downgrade schema.

    Drops both tables: every monitor and its whole check history is lost.
    """
    op.drop_index(
        "ix_checks_scheduled_at_brin", table_name="checks", postgresql_using="brin"
    )
    op.drop_table("checks")
    op.drop_table("monitors")
