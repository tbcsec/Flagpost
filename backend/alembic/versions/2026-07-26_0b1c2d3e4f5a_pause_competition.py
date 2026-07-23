"""pause competition flag

Revision ID: 0b1c2d3e4f5a
Revises: fab0c1d2e3f4
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0b1c2d3e4f5a"
down_revision = "fab0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("competitions") as batch:
        batch.add_column(
            sa.Column("paused", sa.Boolean(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("competitions") as batch:
        batch.drop_column("paused")
