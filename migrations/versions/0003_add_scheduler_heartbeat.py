"""add scheduler heartbeat

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-28 00:30:37.144566

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # New, empty table: no existing data is touched. The row appears on the
    # scheduler's first tick; until then "never ran" reads as no row.
    op.create_table(
        "scheduler_heartbeat",
        sa.Column(
            "id",
            sa.SmallInteger(),
            server_default=sa.text("1"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_scheduler_heartbeat_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduler_heartbeat")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("scheduler_heartbeat")
