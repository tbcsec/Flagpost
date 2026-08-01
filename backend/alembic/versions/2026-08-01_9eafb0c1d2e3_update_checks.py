"""update check + adoption count (#111)

Revision ID: 9eafb0c1d2e3
Revises: 8d9eafb0c1d2
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9eafb0c1d2e3"
down_revision = "8d9eafb0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default is required, not cosmetic: existing rows need a value for
    # the NOT NULL to hold on an already-populated table.
    op.add_column(
        "site_settings",
        sa.Column(
            "update_checks_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "site_settings",
        sa.Column("last_update_check_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "site_settings",
        sa.Column(
            "last_update_attempt_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "site_settings",
        sa.Column("last_update_check_status", sa.String(), nullable=True),
    )
    op.add_column(
        "site_settings", sa.Column("latest_known_version", sa.String(), nullable=True)
    )
    op.add_column(
        "site_settings",
        sa.Column("dismissed_update_version", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("site_settings", "dismissed_update_version")
    op.drop_column("site_settings", "latest_known_version")
    op.drop_column("site_settings", "last_update_check_status")
    op.drop_column("site_settings", "last_update_attempt_at")
    op.drop_column("site_settings", "last_update_check_at")
    op.drop_column("site_settings", "update_checks_enabled")
