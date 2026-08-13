"""hidden / scheduled-release hints (#213)

Adds ``hints.hidden`` and ``hints.release_at``. A hidden hint is invisible to
competitors until it is published — manually, at ``release_at`` (the scheduler
flips it and emits ``hint.published``), or by the ``publish_hint`` automation.
Both columns default to "visible now" (hidden=false, release_at=null), which is
every existing hint's state, so no backfill is needed.

Revision ID: d9f4a1b2c3e5
Revises: c8e3f0a5b2d4
Create Date: 2026-08-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d9f4a1b2c3e5"
down_revision = "c8e3f0a5b2d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hints") as batch:
        batch.add_column(
            sa.Column(
                "hidden",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column("release_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("hints") as batch:
        batch.drop_column("release_at")
        batch.drop_column("hidden")
