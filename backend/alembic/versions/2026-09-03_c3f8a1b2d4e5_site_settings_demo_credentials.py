"""configurable demo login-credentials card (#360)

Adds ``site_settings.demo_credentials`` — a JSON list of
``{label, description, identifier, password}`` the login page renders as
click-to-sign-in buttons on a demo instance (data-driven, so a custom baseline
carries its own demo accounts). Defaults to an empty list; only ever exposed or
rendered when demo_mode is on.

Plain ``add_column`` with a ``[]`` server default so existing rows backfill
without a data migration. JSON default literal works on both SQLite and
Postgres (verified against real Postgres — migrations aren't covered by the
SQLite test suite, ADR-0006).

Revision ID: c3f8a1b2d4e5
Revises: b7d3e9f4a2c1
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3f8a1b2d4e5"
down_revision = "b7d3e9f4a2c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "site_settings",
        sa.Column(
            "demo_credentials",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("site_settings", "demo_credentials")
