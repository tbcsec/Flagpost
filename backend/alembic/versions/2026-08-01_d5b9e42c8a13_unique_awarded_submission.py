"""at most one awarded submission per (challenge, subject)

Revision ID: d5b9e42c8a13
Revises: c4a8d35b1e07
Create Date: 2026-08-01

"The first correct submission is authoritative" was enforced only by a
read-then-write in the submit route: query whether the subject had solved the
challenge, then insert. Two concurrent submissions of the same correct flag both
read "not solved" before either committed, so both were awarded full points. A
competitor holding a flag could bank it N times from one burst.

**The dedupe has to run before the index can exist.** Any install that has been
raced already holds rows the constraint forbids, and `CREATE UNIQUE INDEX` on
that data fails — taking the whole upgrade with it. So collapse existing
duplicates first, keeping the earliest awarded row per (challenge, subject) and
demoting the rest to the duplicates they should have been.

Both statements are portable to SQLite and Postgres: window functions (SQLite
3.25+), and `TRUE` rather than `1` for the boolean, which SQLite accepts and
Postgres requires.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d5b9e42c8a13"
down_revision = "c4a8d35b1e07"
branch_labels = None
depends_on = None

_AWARDED = "is_correct AND NOT is_duplicate"


def upgrade() -> None:
    # Collapse any pre-existing duplicates. Ordered by created_at then id so the
    # survivor is deterministic and matches what the scoreboard already showed:
    # the earliest solve. The demoted rows keep their history — only their
    # scoring flags change, so the attempt log stays complete (§13.2).
    op.execute(
        f"""
        UPDATE submissions
        SET is_duplicate = TRUE, points_awarded = 0
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY challenge_id, COALESCE(team_id, user_id)
                           ORDER BY created_at, id
                       ) AS rn
                FROM submissions
                WHERE {_AWARDED}
            ) ranked
            WHERE ranked.rn > 1
        )
        """
    )

    op.create_index(
        "uq_submissions_awarded_subject",
        "submissions",
        ["challenge_id", sa.text("COALESCE(team_id, user_id)")],
        unique=True,
        sqlite_where=sa.text(_AWARDED),
        postgresql_where=sa.text(_AWARDED),
    )


def downgrade() -> None:
    # A later SQLite batch table-rebuild (e.g. a drop_column on submissions)
    # silently drops this expression/partial index — SQLAlchemy's reflection
    # can't round-trip it — so by the time a downgrade reaches here it may already
    # be gone (#7). Tolerate that instead of wedging the whole downgrade chain.
    try:
        op.drop_index("uq_submissions_awarded_subject", table_name="submissions")
    except sa.exc.OperationalError:
        pass
