"""site-wide animated background style (#195)

Adds ``site_settings.background_style`` — the front-door animated background an
operator selects in Admin → Site settings → Appearance. A slug ("none" |
"aurora" | "gradient" | "constellation"); the frontend owns the actual set and
renders "none" for anything it doesn't know, so this is a string, not an enum.

Revision ID: b7d2e9f4a1c3
Revises: f3a9c1d7e250
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7d2e9f4a1c3"
down_revision = "f3a9c1d7e250"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOT NULL with a server_default so every existing install back-fills to
    # "none" (today's flat ground) — Postgres rejects a NOT NULL add otherwise.
    with op.batch_alter_table("site_settings") as batch:
        batch.add_column(
            sa.Column(
                "background_style",
                sa.String(),
                nullable=False,
                server_default="none",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.drop_column("background_style")
