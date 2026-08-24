"""username_changes_enabled — site toggle for self-service renames (#298)

Adds ``site_settings.username_changes_enabled``: whether accounts may rename
themselves from the profile page. Server default TRUE, so existing installs
keep today's behaviour and nothing is backfilled. Off gates only the
self-service route — an admin rename (manage_users) is unaffected.

Revision ID: e7b2c94a63d1
Revises: d1a6b83f47c2
Create Date: 2026-08-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7b2c94a63d1"
down_revision = "d1a6b83f47c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.add_column(
            sa.Column(
                "username_changes_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.drop_column("username_changes_enabled")
