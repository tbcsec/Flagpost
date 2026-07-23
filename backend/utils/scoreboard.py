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

from db import UtcDateTime, ensure_aware_utc, utcnow
from models.automation import Achievement
from models.challenge import Challenge
from models.competition import Competition
from models.hint import HintReveal
from models.role import Role, RoleAssignment
from models.score_adjustment import ScoreAdjustment
from models.submission import Submission
from models.team import Team
from models.user import User
from utils.brackets import brackets_by_subject
from utils.scoring import challenge_value


async def _hint_costs_by_subject(
    db: AsyncSession, competition_id: str, team_mode: bool, as_of=None
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
    stmt = (
        select(group_col, func.sum(HintReveal.cost_charged))
        .where(HintReveal.competition_id == competition_id, scope)
        .group_by(group_col)
    )
    if as_of is not None:
        stmt = stmt.where(HintReveal.created_at <= as_of)
    rows = (await db.execute(stmt)).all()
    return {subject_id: int(cost or 0) for subject_id, cost in rows}


async def _adjustments_by_subject(
    db: AsyncSession, competition_id: str, team_mode: bool, as_of=None
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
    stmt = (
        select(group_col, func.sum(ScoreAdjustment.points))
        .where(ScoreAdjustment.competition_id == competition_id, scope)
        .group_by(group_col)
    )
    if as_of is not None:
        stmt = stmt.where(ScoreAdjustment.created_at <= as_of)
    rows = (await db.execute(stmt)).all()
    return {subject_id: int(points or 0) for subject_id, points in rows}


async def _award_points_by_subject(
    db: AsyncSession, competition_id: str, team_mode: bool, as_of=None
) -> dict[str, int]:
    """Per-subject sum of award (``Achievement``) point values.

    Awards carry a point value (§5.3 ``create_award`` + manual judge awards)
    that counts toward the score, grouped exactly like score adjustments: by
    credited team in team-mode, by user (team_id NULL) in individual-mode.
    """
    group_col = Achievement.team_id if team_mode else Achievement.user_id
    scope = (
        Achievement.team_id.isnot(None)
        if team_mode
        else Achievement.team_id.is_(None)
    )
    stmt = (
        select(group_col, func.sum(Achievement.points))
        .where(Achievement.competition_id == competition_id, scope)
        .group_by(group_col)
    )
    if as_of is not None:
        stmt = stmt.where(Achievement.created_at <= as_of)
    rows = (await db.execute(stmt)).all()
    return {subject_id: int(points or 0) for subject_id, points in rows}


def freeze_cutoff(competition: Competition):
    """The instant the board is frozen at, if the freeze is in effect right now
    (set and reached); otherwise ``None`` (live board). Scoreboard freeze (§13,
    Phase 9): standings stop moving publicly once this time passes."""
    frozen_at = getattr(competition, "scoreboard_frozen_at", None)
    if frozen_at is None:
        return None
    frozen_at = ensure_aware_utc(frozen_at)
    return frozen_at if utcnow() >= frozen_at else None


async def _awarded_by_subject(
    db: AsyncSession, competition: Competition, team_mode: bool, as_of
) -> dict[str, tuple[int, object]]:
    """Per-subject (points from solves, last solve time).

    Live (``as_of`` None): sum the frozen ``points_awarded`` — the fast path,
    already correct because dynamic solves are re-valued in place on each solve.
    Frozen (``as_of`` set): recompute in Python as of the cutoff, so a dynamic
    challenge is valued by its solve count *at freeze time* and only pre-cutoff
    solvers count. Only runs while a board is frozen (end-game), so the extra
    work is fine."""
    subj_col = Submission.team_id if team_mode else Submission.user_id
    scope = (
        Submission.team_id.isnot(None)
        if team_mode
        else Submission.team_id.is_(None)
    )
    base = (
        Submission.competition_id == competition.id,
        Submission.is_correct.is_(True),
        Submission.is_duplicate.is_(False),
        scope,
    )
    if as_of is None:
        rows = (
            await db.execute(
                select(
                    subj_col,
                    func.sum(Submission.points_awarded),
                    type_coerce(func.max(Submission.created_at), UtcDateTime()),
                )
                .where(*base)
                .group_by(subj_col)
            )
        ).all()
        return {sid: (int(pts or 0), last) for sid, pts, last in rows}

    # Frozen: fetch solves up to the cutoff and value each challenge by its
    # solve count as of then (the CTFd freeze semantics for dynamic scoring).
    rows = (
        await db.execute(
            select(Submission.challenge_id, subj_col, Submission.created_at).where(
                *base, Submission.created_at <= as_of
            )
        )
    ).all()
    counts: dict[str, int] = {}
    for chid, _subj, _ts in rows:
        counts[chid] = counts.get(chid, 0) + 1
    challenges = {
        c.id: c
        for c in (
            await db.execute(
                select(Challenge).where(Challenge.competition_id == competition.id)
            )
        ).scalars()
    }
    totals: dict[str, tuple[int, object]] = {}
    for chid, subj, ts in rows:
        ch = challenges.get(chid)
        value = challenge_value(ch, counts[chid]) if ch is not None else 0
        pts, last = totals.get(subj, (0, ts))
        totals[subj] = (pts + value, ts if last is None or ts > last else last)
    return totals


async def compute_scoreboard(
    db: AsyncSession,
    competition: Competition,
    *,
    live: bool = False,
    bracket: str | None = None,
) -> dict[str, Any]:
    """Return the ranked scoreboard as a JSON-serializable dict.

    ``live=True`` bypasses a scoreboard freeze (§13, Phase 9) so a staff caller
    can see the true standings; otherwise a frozen board is computed **as of**
    the freeze instant, so standings publicly stop moving once it passes.
    ``bracket`` filters to one division and ranks within it (Phase 9, Group C).
    """
    team_mode = competition.participation_mode == "team"
    as_of = None if live else freeze_cutoff(competition)

    hint_costs = await _hint_costs_by_subject(db, competition.id, team_mode, as_of)
    adjustments = await _adjustments_by_subject(db, competition.id, team_mode, as_of)
    award_points = await _award_points_by_subject(db, competition.id, team_mode, as_of)
    awarded = await _awarded_by_subject(db, competition, team_mode, as_of)
    subject_brackets = await brackets_by_subject(db, competition.id)

    # The ranked entities (every registered subject, scored or not).
    if team_mode:
        subjects = (
            await db.execute(
                select(Team.id, Team.name).where(
                    Team.competition_id == competition.id
                )
            )
        ).all()
    else:
        # Individual-mode ranks every holder of the competition-scoped
        # Participant role (§7.5); solo submissions carry team_id NULL.
        subjects = (
            await db.execute(
                select(User.id, User.display_name)
                .join(RoleAssignment, RoleAssignment.user_id == User.id)
                .join(Role, Role.id == RoleAssignment.role_id)
                .where(
                    RoleAssignment.competition_id == competition.id,
                    Role.name == "Participant",
                )
                .distinct()
            )
        ).all()

    # A bracket filter ranks within that division only.
    if bracket is not None:
        subjects = [s for s in subjects if subject_brackets.get(s[0]) == bracket]

    # Net points = awarded solves − hint costs + signed adjustments (§5.3
    # update_score) + award points (§5.3 create_award / manual awards), clamped
    # at 0 (nothing drags a subject below zero). The tie-break stays the last
    # *solve* time — hints, adjustments and awards move the total, but they
    # aren't scoring events.
    def net_points(subject_id) -> int:
        earned, _ = awarded.get(subject_id, (0, None))
        return max(
            0,
            earned
            - hint_costs.get(subject_id, 0)
            + adjustments.get(subject_id, 0)
            + award_points.get(subject_id, 0),
        )

    def sort_key(row):
        subject_id, name = row
        _, last_solve_at = awarded.get(subject_id, (0, None))
        # Solveless subjects sort after scored ones at the same point total via
        # the flag, so real datetimes are only ever compared with each other
        # (they share tz-awareness; a naive datetime.min constant would not).
        return (
            -net_points(subject_id),
            1 if last_solve_at is None else 0,
            last_solve_at or datetime.min,
            (name or "").lower(),
        )

    entries = []
    for rank, (subject_id, name) in enumerate(
        sorted(subjects, key=sort_key), start=1
    ):
        _, last_solve_at = awarded.get(subject_id, (0, None))
        entries.append(
            {
                "rank": rank,
                "subject_id": subject_id,
                "name": name,
                "points": net_points(subject_id),
                "last_solve_at": (
                    last_solve_at.isoformat() if last_solve_at is not None else None
                ),
                "bracket": subject_brackets.get(subject_id),
            }
        )

    return {
        "competition_id": competition.id,
        "mode": competition.participation_mode,
        "entries": entries,
        "frozen": as_of is not None,
        "frozen_at": as_of.isoformat() if as_of is not None else None,
        "brackets": list(competition.brackets or []),
    }
