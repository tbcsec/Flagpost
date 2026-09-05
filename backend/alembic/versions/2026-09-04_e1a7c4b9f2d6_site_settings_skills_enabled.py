"""site-wide skills web switch (#364, ADR-0039)

Adds ``site_settings.skills_enabled`` — the on/off for the cross-competition
skills web. On by default; when off both skills reads 404 and the UI hides.

Plain ``add_column`` with a ``"1"`` (true) server default so existing rows
backfill without a data migration. Verified against real Postgres — migrations
aren't covered by the SQLite test suite (ADR-0006).

Revision ID: e1a7c4b9f2d6
Revises: c3f8a1b2d4e5
Create Date: 2026-09-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e1a7c4b9f2d6"
down_revision = "c3f8a1b2d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "site_settings",
        sa.Column(
            "skills_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("site_settings", "skills_enabled")
