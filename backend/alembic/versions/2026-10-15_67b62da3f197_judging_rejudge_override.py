"""judgings.origin/requested_by/note + code_submissions.submission_id (#450)

Rejudging and verdict overrides add judgings to a code submission rather than
rewriting one, so a judging records why it exists (``origin``), who asked, and
an override's reason. A code submission's score now lives on one Submission
row for all its judgings (``code_submissions.submission_id``), backfilled from
the one judging every existing code submission has.

Revision ID: 67b62da3f197
Revises: 841ce13a0a92
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "67b62da3f197"
down_revision = "841ce13a0a92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("judgings") as batch:
        batch.add_column(
            sa.Column("origin", sa.String(), nullable=False, server_default="submission")
        )
        batch.add_column(
            sa.Column(
                "requested_by_user_id",
                sa.String(),
                sa.ForeignKey(
                    "users.id",
                    ondelete="SET NULL",
                    name="fk_judgings_requested_by_user_id_users",
                ),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("note", sa.Text(), nullable=True))
    with op.batch_alter_table("code_submissions") as batch:
        batch.add_column(
            sa.Column(
                "submission_id",
                sa.String(),
                sa.ForeignKey(
                    "submissions.id",
                    ondelete="SET NULL",
                    name="fk_code_submissions_submission_id_submissions",
                ),
                nullable=True,
            )
        )
    op.execute(
        "UPDATE code_submissions SET submission_id = ("
        " SELECT j.submission_id FROM judgings j"
        " WHERE j.code_submission_id = code_submissions.id"
        " AND j.submission_id IS NOT NULL LIMIT 1)"
    )


def downgrade() -> None:
    with op.batch_alter_table("code_submissions") as batch:
        batch.drop_column("submission_id")
    with op.batch_alter_table("judgings") as batch:
        batch.drop_column("note")
        batch.drop_column("requested_by_user_id")
        batch.drop_column("origin")
