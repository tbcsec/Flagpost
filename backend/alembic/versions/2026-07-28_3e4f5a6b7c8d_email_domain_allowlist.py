"""email domain allowlist for public registration (#56)

Site-wide settings gate: an enabled flag + a JSON domain list, both nullable-
safe defaults (off, no list) so an existing install's registration behaviour
is unchanged until an admin opts in on Admin -> Site settings.

Revision ID: 3e4f5a6b7c8d
Revises: 2d3e4f5a6b7c
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "3e4f5a6b7c8d"
down_revision = "2d3e4f5a6b7c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.add_column(
            sa.Column(
                "email_domain_allowlist_enabled",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(sa.Column("allowed_email_domains", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.drop_column("allowed_email_domains")
        batch.drop_column("email_domain_allowlist_enabled")
