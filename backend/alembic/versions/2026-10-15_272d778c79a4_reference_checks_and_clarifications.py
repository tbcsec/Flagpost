"""reference checks + clarifications (#450, part 2)

- ``judgings.problem_version``: a fingerprint of the test data and limits a
  judging ran against, so an author's reference-solution check can tell it's
  out of date once the problem changes.
- ``announcements.kind`` / ``challenge_id`` / ``question``: a clarification is
  an announcement about one challenge, answering a question (never storing who
  asked). Existing rows are ordinary announcements.
- ``ticket_messages.sent_to_all``: a staff answer that also went to everyone.
- ``tickets.kind``: ``question`` for a competitor's question about a challenge,
  asked from its page (read-only for the asker once sent); every existing
  ticket is ``support``.

Revision ID: 272d778c79a4
Revises: 67b62da3f197
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "272d778c79a4"
down_revision = "67b62da3f197"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("judgings") as batch:
        batch.add_column(sa.Column("problem_version", sa.String(), nullable=True))
    with op.batch_alter_table("announcements") as batch:
        batch.add_column(
            sa.Column("kind", sa.String(), nullable=False, server_default="announcement")
        )
        batch.add_column(
            sa.Column(
                "challenge_id",
                sa.String(),
                sa.ForeignKey(
                    "challenges.id",
                    ondelete="CASCADE",
                    name="fk_announcements_challenge_id_challenges",
                ),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("question", sa.Text(), nullable=True))
        batch.create_index("ix_announcements_challenge_id", ["challenge_id"])
    with op.batch_alter_table("ticket_messages") as batch:
        batch.add_column(
            sa.Column("sent_to_all", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("tickets") as batch:
        batch.add_column(
            sa.Column("kind", sa.String(), nullable=False, server_default="support")
        )


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch:
        batch.drop_column("kind")
    with op.batch_alter_table("ticket_messages") as batch:
        batch.drop_column("sent_to_all")
    with op.batch_alter_table("announcements") as batch:
        batch.drop_index("ix_announcements_challenge_id")
        batch.drop_column("question")
        batch.drop_column("challenge_id")
        batch.drop_column("kind")
    with op.batch_alter_table("judgings") as batch:
        batch.drop_column("problem_version")
