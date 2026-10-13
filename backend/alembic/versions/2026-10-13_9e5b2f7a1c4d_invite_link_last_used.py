"""invite_links.last_used_at (#427 Phase 4)

When a link last admitted someone — the organiser's "is this link still
circulating?" signal, same new-join semantics as ``use_count``. Nullable add,
backfill-free: existing links read as never-used, which is accurate for the
column's lifetime.

Revision ID: 9e5b2f7a1c4d
Revises: 7c3d9e1f4a8b
Create Date: 2026-10-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9e5b2f7a1c4d"
down_revision = "7c3d9e1f4a8b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "invite_links",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invite_links", "last_used_at")
