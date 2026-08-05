"""ai_competition_settings + ai_disclosure_acceptances (#98, ADR-0023 Phase 3)

Per-competition competitor-assistant controls — one row per competition
(competition_id is the primary key): the competitor assistant on/off toggle, an
optional guidance-level override (NULL inherits the site default), and the hard
challenge-metadata data toggle. Cascades from its competition, so it purges with
the competition (retention follows the lifecycle).

Plus the per-user first-run disclosure acceptance (one row per user, cascades
from the user) — creating a competitor conversation is refused until it exists.

Revision ID: d5b3e2c9a710
Revises: a1e7c93bd42f
Create Date: 2026-08-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d5b3e2c9a710"
down_revision = "a1e7c93bd42f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_competition_settings",
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column(
            "competitor_enabled", sa.Boolean(), server_default="0", nullable=False
        ),
        sa.Column("guidance_level", sa.String(), nullable=True),
        sa.Column(
            "challenge_metadata_access",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["competitions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("competition_id"),
    )

    op.create_table(
        "ai_disclosure_acceptances",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("ai_disclosure_acceptances")
    op.drop_table("ai_competition_settings")
