"""add next_check_at to monitors

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27 23:35:36.145671

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing monitors get the migration's time, so they are all due at once
    # and get checked right away. now() is not volatile, so PostgreSQL stores
    # it as a default instead of rewriting the table.
    op.add_column(
        "monitors",
        sa.Column(
            "next_check_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_monitors_next_check_at_active",
        "monitors",
        ["next_check_at"],
        unique=False,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_monitors_next_check_at_active",
        table_name="monitors",
        postgresql_where=sa.text("is_active"),
    )
    op.drop_column("monitors", "next_check_at")
