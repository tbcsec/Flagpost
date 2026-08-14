"""competition status lifecycle — not_started/running/ended gate (#221)

Adds ``competitions.status`` (``not_started`` | ``running`` | ``ended``), the
gate on competitor access (challenge viewing/submission + scoreboard). New
competitions default ``not_started`` via the server default.

Existing competitions are **backfilled** from their schedule/now so nothing live
breaks: a competition past its ``end_at`` becomes ``ended``; one with no start or
a start already reached becomes ``running``; one whose ``start_at`` is still in
the future becomes ``not_started``. The scheduler's ``started_event_fired`` /
``ended_event_fired`` dedup flags are aligned to the derived status so the first
post-migration tick can't contradict it or emit a spurious lifecycle event.

The backfill runs in Python (not raw SQL) so the datetime comparison is correct
on both SQLite (naive) and Postgres (aware) — see ADR-0006.

Revision ID: c5d9a3f21b60
Revises: a4e1c9b7f2d3
Create Date: 2026-08-14
"""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "c5d9a3f21b60"
down_revision = "a4e1c9b7f2d3"
branch_labels = None
depends_on = None


_competitions = sa.table(
    "competitions",
    sa.column("id", sa.String),
    sa.column("start_at", sa.DateTime(timezone=True)),
    sa.column("end_at", sa.DateTime(timezone=True)),
    sa.column("status", sa.String),
    sa.column("started_event_fired", sa.Boolean),
    sa.column("ended_event_fired", sa.Boolean),
)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands datetimes back naive; treat those as UTC before comparing."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def upgrade() -> None:
    op.add_column(
        "competitions",
        sa.Column("status", sa.String(), nullable=False, server_default="not_started"),
    )

    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    rows = conn.execute(
        sa.select(_competitions.c.id, _competitions.c.start_at, _competitions.c.end_at)
    ).fetchall()
    for row in rows:
        start_at = _aware(row.start_at)
        end_at = _aware(row.end_at)
        if end_at is not None and end_at < now:
            status = "ended"
        elif start_at is None:
            status = "running"  # open-ended competitions have effectively started
        elif start_at > now:
            status = "not_started"
        else:
            status = "running"
        conn.execute(
            _competitions.update()
            .where(_competitions.c.id == row.id)
            .values(
                status=status,
                started_event_fired=status in ("running", "ended"),
                ended_event_fired=status == "ended",
            )
        )


def downgrade() -> None:
    op.drop_column("competitions", "status")
