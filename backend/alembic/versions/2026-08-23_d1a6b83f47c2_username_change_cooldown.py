"""username change cooldown — track when a user last renamed themselves

Adds ``users.username_changed_at``: the timestamp of the last self-service (or
admin) display-name change, driving the 30-day cooldown. Nullable, no default,
nothing backfilled — every existing account reads as "never changed", so no one
is under a cooldown after this migration and behaviour is unchanged until the
first rename.

Revision ID: d1a6b83f47c2
Revises: c9f4a7d215e8
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d1a6b83f47c2"
down_revision = "c9f4a7d215e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("username_changed_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("username_changed_at")
