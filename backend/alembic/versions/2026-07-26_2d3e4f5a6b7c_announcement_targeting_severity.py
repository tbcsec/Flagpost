"""announcement severity + audience targeting (#40)

Existing announcements pick up the server defaults (info / all), so they keep
behaving exactly as before: whole-competition, informational.

Revision ID: 2d3e4f5a6b7c
Revises: 1c2d3e4f5a6b
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "2d3e4f5a6b7c"
down_revision = "1c2d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("announcements") as batch:
        batch.add_column(
            sa.Column(
                "severity", sa.String(), nullable=False, server_default="info"
            )
        )
        batch.add_column(
            sa.Column(
                "audience_type", sa.String(), nullable=False, server_default="all"
            )
        )
        batch.add_column(sa.Column("audience_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("announcements") as batch:
        batch.drop_column("audience_ids")
        batch.drop_column("audience_type")
        batch.drop_column("severity")
