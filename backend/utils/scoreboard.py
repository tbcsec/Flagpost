"""Scoreboard computation (ROADMAP #13, ARCHITECTURE.md §13.2, §15).

Ranks the competition's scoring subjects — teams in team-mode, users in
individual-mode (the same subject `utils/scoring` credits solves to). Points
are the sum of awarded submissions; duplicates carry 0 by construction.

Ranking: points descending, ties broken by **earliest time reaching the
current score** (the §15 open question, resolved to the standard CTF
convention) — i.e. the earlier last awarded solve wins the tie — then name for
a stable order. Subjects with no solves rank below scored ones, alphabetically.

Every registered subject appears, not just scorers: all teams in team-mode,
every holder of a competition-scoped Participant role in individual-mode — so
the board is alive from the moment people join, not only after first blood.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession

from db import UtcDateTime
from models.competition import Competition
from models.hint import HintReveal
from models.role import Role, RoleAssignment
from models.score_adjustment import ScoreAdjustment
from models.submission import Submission
from models.team import Team
from models.user import User


def _awarded_totals(competition_id: str, group_col):
    """Subquery: per-subject total points + time of the last awarded solve.

    ``type_coerce`` keeps the DateTime result processor on the aggregate so
    SQLite (which stores datetimes as text) still returns real datetimes
    (ADR-0006 portability).
    """
    return (
        select(
            group_col.label("subject_id"),
            func.sum(Submission.points_awarded).label("points"),
            type_coerce(func.max(Submission.created_at), UtcDateTime()).label(
                "last_solve_at"
            ),
        )
        .where(
            Submission.competition_id == competition_id,
            Submission.is_correct.is_(True),
            Submission.is_duplicate.is_(False),
        )
        .group_by(group_col)
        .subquery()
    )


async def _hint_costs_by_subject(
    db: AsyncSession, competition_id: str, team_mode: bool
) -> dict[str, int]:
    """Per-subject total hint cost paid, keyed like the awarded totals (Phase 9)."""
    group_col = HintReveal.team_id if team_mode else HintReveal.user_id
    # Team-mode groups by the credited team; individual-mode by the user, and
    # only their solo reveals (team_id NULL) so a stray team row can't bleed in.
    scope = (
        HintReveal.team_id.isnot(None)
        if team_mode
        else HintReveal.team_id.is_(None)
    )
    rows = (
        await db.execute(
            select(group_col, func.sum(HintReveal.cost_charged))
            .where(HintReveal.competition_id == competition_id, scope)
            .group_by(group_col)
        )
    ).all()
    return {subject_id: int(cost or 0) for subject_id, cost in rows}


async def _adjustments_by_subject(
    db: AsyncSession, competition_id: str, team_mode: bool
) -> dict[str, int]:
    """Per-subject signed score-adjustment total (§5.3 ``update_score``).

    Grouped exactly like hint costs: by credited team in team-mode, by user
    (team_id NULL) in individual-mode — the §13.2 subject semantics the
    adjustment rows are written with.
    """
    group_col = ScoreAdjustment.team_id if team_mode else ScoreAdjustment.user_id
    scope = (
        ScoreAdjustment.team_id.isnot(None)
        if team_mode
        else ScoreAdjustment.team_id.is_(None)
    )
    rows = (
        await db.execute(
            select(group_col, func.sum(ScoreAdjustment.points))
            .where(ScoreAdjustment.competition_id == competition_id, scope)
            .group_by(group_col)
        )
    ).all()
    return {subject_id: int(points or 0) for subject_id, points in rows}


async def compute_scoreboard(
    db: AsyncSession, competition: Competition
) -> dict[str, Any]:
    """Return the ranked scoreboard as a JSON-serializable dict."""
    team_mode = competition.participation_mode == "team"
    hint_costs = await _hint_costs_by_subject(db, competition.id, team_mode)
    adjustments = await _adjustments_by_subject(db, competition.id, team_mode)
    if competition.participation_mode == "team":
        totals = _awarded_totals(competition.id, Submission.team_id)
        rows = (
            await db.execute(
                select(
                    Team.id,
                    Team.name,
                    totals.c.points,
                    totals.c.last_solve_at,
                )
                .outerjoin(totals, totals.c.subject_id == Team.id)
                .where(Team.competition_id == competition.id)
            )
        ).all()
    else:
        totals = _awarded_totals(competition.id, Submission.user_id)
        # Individual-mode boards rank everyone holding the competition-scoped
        # Participant role (§7.5) — solo submissions carry team_id NULL, and the
        # totals subquery is already scoped to this competition.
        rows = (
            await db.execute(
                select(
                    User.id,
                    User.display_name,
                    totals.c.points,
                    totals.c.last_solve_at,
                )
                .join(RoleAssignment, RoleAssignment.user_id == User.id)
                .join(Role, Role.id == RoleAssignment.role_id)
                .outerjoin(totals, totals.c.subject_id == User.id)
                .where(
                    RoleAssignment.competition_id == competition.id,
                    Role.name == "Participant",
                )
                .distinct()
            )
        ).all()

    # Net points = awarded solves − hint costs + signed adjustments (§5.3
    # update_score), clamped at 0 (nothing drags a subject below zero). The
    # tie-break stays the last *solve* time — hints and adjustments move the
    # total, but they aren't scoring events.
    def net_points(subject_id, awarded) -> int:
        return max(
            0,
            int(awarded or 0)
            - hint_costs.get(subject_id, 0)
            + adjustments.get(subject_id, 0),
        )

    def sort_key(row):
        subject_id, name, points, last_solve_at = row
        # Solveless subjects sort after scored ones at the same point total via
        # the flag, so real datetimes are only ever compared with each other
        # (they share tz-awareness; a naive datetime.min constant would not).
        return (
            -net_points(subject_id, points),
            1 if last_solve_at is None else 0,
            last_solve_at or datetime.min,
            (name or "").lower(),
        )

    entries = []
    for rank, (subject_id, name, points, last_solve_at) in enumerate(
        sorted(rows, key=sort_key), start=1
    ):
        entries.append(
            {
                "rank": rank,
                "subject_id": subject_id,
                "name": name,
                "points": net_points(subject_id, points),
                "last_solve_at": (
                    last_solve_at.isoformat() if last_solve_at is not None else None
                ),
            }
        )

    return {
        "competition_id": competition.id,
        "mode": competition.participation_mode,
        "entries": entries,
    }
