"""custom brand theme presets (#323, ADR-0011)

Adds ``theme_presets`` — site-level custom brand themes, each a complete pack of
the design tokens the UI runs on (see ``models/theme_preset.py``,
``utils/theme_tokens.py``). Site-wide, so no ``competition_id``.

Purely additive: nothing reads the table until the feature ships, and
``site_settings.default_palette`` keeps its current meaning (it may now name a
preset id in addition to a built-in palette slug). The 2–3 ``source="builtin"``
example presets are seeded lazily on first boot (``utils.theme_seed``), not by
this migration, so they also appear in the test/dev SQLite build.

Revision ID: c7e2f1a9b3d4
Revises: b4e1f7a3c8d9
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c7e2f1a9b3d4"
down_revision = "b4e1f7a3c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "theme_presets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("tokens", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="custom"),
        sa.Column(
            "created_by",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("theme_presets")
