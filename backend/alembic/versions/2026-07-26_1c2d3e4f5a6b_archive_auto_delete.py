"""archived-competition auto-delete (#26)

Site-wide retention settings (default ON at 30 days — consent happens at
archive time via the confirm dialog) + the per-competition purge_after clock.
Existing rows: settings pick up the server defaults; competitions get NULL
purge_after, so nothing already archived is ever scheduled retroactively.

Revision ID: 1c2d3e4f5a6b
Revises: 0b1c2d3e4f5a
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "1c2d3e4f5a6b"
down_revision = "0b1c2d3e4f5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.add_column(
            sa.Column(
                "archive_auto_delete",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            )
        )
        batch.add_column(
            sa.Column(
                "archive_retention_days",
                sa.Integer(),
                nullable=False,
                server_default="30",
            )
        )
    with op.batch_alter_table("competitions") as batch:
        batch.add_column(
            sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("competitions") as batch:
        batch.drop_column("purge_after")
    with op.batch_alter_table("site_settings") as batch:
        batch.drop_column("archive_retention_days")
        batch.drop_column("archive_auto_delete")
