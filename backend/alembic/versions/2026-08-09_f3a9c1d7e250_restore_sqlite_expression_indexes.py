"""restore SQLite expression/partial indexes lost to a batch table-rebuild (#7)

On SQLite, ``batch_alter_table`` recreates a table and only the indexes its
reflection can round-trip — an expression or partial index (``COALESCE(...)``,
``lower(...)``, ``WHERE ...``) is silently dropped. So after a migration that
rebuilds ``submissions`` or ``users`` (a ``drop_column``), two guarantees quietly
vanish on the SQLite dev/preview stack:

- ``uq_submissions_awarded_subject`` — the partial UNIQUE index the submit route
  relies on to make "one awarded row per (challenge, subject)" a schema property
  (the anti-double-award guard).
- ``uq_users_display_name_lower`` — case-insensitive uniqueness of the login handle.

This heals both: it recreates them ``IF NOT EXISTS`` at head, so any ``upgrade
head`` restores them after a down->up cycle. SQLite-only — Postgres degrades
``batch`` to a native ALTER that never rebuilds the table, so it never loses them
(and this migration is a no-op there). The submissions dedupe mirrors the
original migration so a re-create can't fail on rows a reopened race left behind.

Revision ID: f3a9c1d7e250
Revises: a2f4c8d1e6b7
Create Date: 2026-08-09
"""

from __future__ import annotations

from alembic import op

revision = "f3a9c1d7e250"
down_revision = "a2f4c8d1e6b7"
branch_labels = None
depends_on = None

_AWARDED = "is_correct AND NOT is_duplicate"


def upgrade() -> None:
    # Postgres never loses these (no table rebuild), so scope the heal to SQLite
    # and avoid re-rendering the per-dialect index SQL.
    if op.get_bind().dialect.name != "sqlite":
        return

    # Collapse any duplicates a race reopened while the unique index was absent,
    # so the re-create can't abort — same survivor rule as the original migration.
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
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_submissions_awarded_subject "
        f"ON submissions (challenge_id, COALESCE(team_id, user_id)) WHERE {_AWARDED}"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_display_name_lower "
        "ON users (lower(display_name))"
    )


def downgrade() -> None:
    # These indexes are owned by their original migrations; this one only heals
    # SQLite's reflection loss, so its downgrade is intentionally a no-op.
    pass
