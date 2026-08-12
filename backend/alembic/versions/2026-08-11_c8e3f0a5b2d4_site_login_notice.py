"""custom sign-in notice (#197)

Adds ``site_settings.login_notice`` — an admin-authored rich-text (ProseMirror
JSON) document rendered above the sign-in card on /login. Nullable; null means
no notice, which is every existing install's state, so no backfill is needed.

Revision ID: c8e3f0a5b2d4
Revises: b7d2e9f4a1c3
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8e3f0a5b2d4"
down_revision = "b7d2e9f4a1c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.add_column(sa.Column("login_notice", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.drop_column("login_notice")
