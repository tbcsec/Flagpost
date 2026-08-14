"""certificate preset colours — per-template accent/base overrides (#219)

Adds ``certificate_templates.preset_accent`` and ``preset_base``: optional hex
overrides for a preset background's two adjustable colours (mirroring the
site-branding accent/base model). Null = use the preset's built-in default, so
existing templates are unaffected.

Revision ID: f3b8c21d9e07
Revises: e1a7c93f5b28
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3b8c21d9e07"
down_revision = "e1a7c93f5b28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("certificate_templates") as batch:
        batch.add_column(sa.Column("preset_accent", sa.String(), nullable=True))
        batch.add_column(sa.Column("preset_base", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("certificate_templates") as batch:
        batch.drop_column("preset_base")
        batch.drop_column("preset_accent")
