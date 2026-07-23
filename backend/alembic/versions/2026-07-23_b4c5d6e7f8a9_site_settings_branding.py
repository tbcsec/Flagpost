"""site_settings custom logo + wordmark toggle (branding)

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-23

Adds the custom-logo blob (+ its content-type / last-updated) and the
``show_wordmark`` toggle to the site-settings singleton. The logo lives in the
DB (not object storage) so branding works on the infra-free stack and pre-auth.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.add_column(sa.Column("logo_data", sa.LargeBinary(), nullable=True))
        batch.add_column(
            sa.Column("logo_content_type", sa.String(), nullable=True)
        )
        batch.add_column(
            sa.Column("logo_updated_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "show_wordmark",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.drop_column("show_wordmark")
        batch.drop_column("logo_updated_at")
        batch.drop_column("logo_content_type")
        batch.drop_column("logo_data")
