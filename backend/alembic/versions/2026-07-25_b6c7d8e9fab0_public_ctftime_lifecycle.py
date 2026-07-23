"""public scoreboard + ctftime toggles + competition lifecycle dedup flags

Revision ID: b6c7d8e9fab0
Revises: a5b6c7d8e9fa
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b6c7d8e9fab0"
down_revision = "a5b6c7d8e9fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("competitions") as batch:
        batch.add_column(
            sa.Column("public_scoreboard", sa.Boolean(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("ctftime_enabled", sa.Boolean(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("started_event_fired", sa.Boolean(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("ended_event_fired", sa.Boolean(), nullable=False, server_default="0")
        )
    # Don't retro-fire started/ended for competitions whose boundaries are
    # already in the past: mark them as already fired.
    op.execute(
        "UPDATE competitions SET started_event_fired = 1 "
        "WHERE start_at IS NOT NULL AND start_at <= CURRENT_TIMESTAMP"
    )
    op.execute(
        "UPDATE competitions SET ended_event_fired = 1 "
        "WHERE end_at IS NOT NULL AND end_at <= CURRENT_TIMESTAMP"
    )


def downgrade() -> None:
    with op.batch_alter_table("competitions") as batch:
        batch.drop_column("ended_event_fired")
        batch.drop_column("started_event_fired")
        batch.drop_column("ctftime_enabled")
        batch.drop_column("public_scoreboard")
