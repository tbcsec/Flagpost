"""rules / code of conduct (#57)

Three pieces: the site-wide rules document (+ display-only flag) on
site_settings, the per-competition override (+ its own flag) on competitions,
and the rules_acceptances table recording which user accepted the effective
document for which competition. All nullable/default-off so existing installs
gain no gate until an admin authors rules text.

Revision ID: 4f5a6b7c8d9e
Revises: 3e4f5a6b7c8d
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "4f5a6b7c8d9e"
down_revision = "3e4f5a6b7c8d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("site_settings") as batch:
        batch.add_column(sa.Column("rules_text", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column(
                "rules_display_only",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )
    with op.batch_alter_table("competitions") as batch:
        batch.add_column(sa.Column("rules_override", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column(
                "rules_display_only",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )
    op.create_table(
        "rules_acceptances",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["competitions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "competition_id",
            "user_id",
            name="uq_rules_acceptance_user_per_competition",
        ),
    )
    op.create_index(
        "ix_rules_acceptances_competition_id", "rules_acceptances", ["competition_id"]
    )
    op.create_index(
        "ix_rules_acceptances_user_id", "rules_acceptances", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("rules_acceptances")
    with op.batch_alter_table("competitions") as batch:
        batch.drop_column("rules_display_only")
        batch.drop_column("rules_override")
    with op.batch_alter_table("site_settings") as batch:
        batch.drop_column("rules_display_only")
        batch.drop_column("rules_text")
