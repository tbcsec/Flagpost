"""Challenge & team analytics aggregation (ROADMAP #23, §13.2).

Read-only reporting derived entirely from data Tier 1 already records — every
submission (success *and* failure, §13.2), hint reveals, and challenge-linked
tickets — so there's no new instrumentation, just aggregation. Everything is
competition-scoped (§6.2); the caller (routers/analytics.py) gates on
``view_competition_analytics``.

Timestamp math (average solve time) is done in Python, not SQL, so it stays
portable across SQLite/Postgres (ADR-0006) — the DB only counts and groups.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import ensure_aware_utc
from models.challenge import Category, Challenge
from models.feedback import ChallengeRating
from models.competition import Competition
from models.hint import HintReveal
from models.role import Role, RoleAssignment
from models.submission import Submission
from models.team import Team
from utils.scoreboard import compute_scoreboard

_AWARDED = (Submission.is_correct.is_(True), Submission.is_duplicate.is_(False))


async def subject_count(db: AsyncSession, competition: Competition) -> int:
    """The number of scoring subjects — teams in team mode, Participant-role
    holders in individual mode (the denominator for completion rate)."""
    if competition.participation_mode == "team":
        return (
            await db.scalar(
                select(func.count(Team.id)).where(
                    Team.competition_id == competition.id
                )
            )
        ) or 0
    return (
        await db.scalar(
            select(func.count(distinct(RoleAssignment.user_id)))
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(
                RoleAssignment.competition_id == competition.id,
                Role.name == "Participant",
            )
        )
    ) or 0


def _solve_time_reference(competition: Competition) -> datetime:
    """When the clock starts for "solve time": the competition's start, or its
    creation if it was never scheduled."""
    start = competition.start_at or competition.created_at
    return ensure_aware_utc(start)


async def challenge_analytics(
    db: AsyncSession, competition: Competition
) -> list[dict[str, Any]]:
    """Per-challenge: solves, attempts/fails, completion rate, average solve
    time, hints used, and linked ticket count."""
    competition_id = competition.id
    reference = _solve_time_reference(competition)
    subjects = await subject_count(db, competition)

    # Attempts + fails per challenge (one grouped count query).
    attempt_rows = (
        await db.execute(
            select(
                Submission.challenge_id,
                func.count(Submission.id),
                func.sum(case((Submission.is_correct.is_(False), 1), else_=0)),
            )
            .where(Submission.competition_id == competition_id)
            .group_by(Submission.challenge_id)
        )
    ).all()
    attempts = {cid: (total, int(fails or 0)) for cid, total, fails in attempt_rows}

    # Awarded (first-correct) submissions carry solve_count + solve timestamps.
    solve_rows = (
        await db.execute(
            select(Submission.challenge_id, Submission.created_at).where(
                Submission.competition_id == competition_id, *_AWARDED
            )
        )
    ).all()
    solve_times: dict[str, list[float]] = {}
    for cid, created_at in solve_rows:
        seconds = (ensure_aware_utc(created_at) - reference).total_seconds()
        solve_times.setdefault(cid, []).append(max(0.0, seconds))

    hint_rows = (
        await db.execute(
            select(HintReveal.challenge_id, func.count(HintReveal.id))
            .where(HintReveal.competition_id == competition_id)
            .group_by(HintReveal.challenge_id)
        )
    ).all()
    hints_used = {cid: count for cid, count in hint_rows}

    # Tickets linked to a challenge (models.ticket.Ticket.challenge_id).
    from models.ticket import Ticket

    ticket_rows = (
        await db.execute(
            select(Ticket.challenge_id, func.count(Ticket.id))
            .where(
                Ticket.competition_id == competition_id,
                Ticket.challenge_id.is_not(None),
            )
            .group_by(Ticket.challenge_id)
        )
    ).all()
    tickets = {cid: count for cid, count in ticket_rows}

    # Post-solve ratings (avg + count) per challenge — which challenges landed well.
    rating_rows = (
        await db.execute(
            select(
                ChallengeRating.challenge_id,
                func.avg(ChallengeRating.rating),
                func.count(ChallengeRating.id),
            )
            .where(ChallengeRating.competition_id == competition_id)
            .group_by(ChallengeRating.challenge_id)
        )
    ).all()
    ratings = {cid: (avg, count) for cid, avg, count in rating_rows}

    challenges = (
        await db.execute(
            select(
                Challenge.id,
                Challenge.title,
                Challenge.points,
                Challenge.state,
                Category.name,
            )
            .outerjoin(Category, Category.id == Challenge.category_id)
            .where(Challenge.competition_id == competition_id)
            .order_by(Challenge.created_at)
        )
    ).all()

    result: list[dict[str, Any]] = []
    for cid, title, points, state, category in challenges:
        times = solve_times.get(cid, [])
        solves = len(times)
        total_attempts, fails = attempts.get(cid, (0, 0))
        result.append(
            {
                "challenge_id": cid,
                "title": title,
                "category": category,
                "points": points,
                "state": state,
                "solve_count": solves,
                "attempt_count": total_attempts,
                "fail_count": fails,
                "completion_rate": (solves / subjects) if subjects else 0.0,
                "avg_solve_time_seconds": (
                    sum(times) / solves if solves else None
                ),
                "hints_used": hints_used.get(cid, 0),
                "ticket_count": tickets.get(cid, 0),
                "avg_rating": (
                    round(float(ratings[cid][0]), 2) if cid in ratings else None
                ),
                "rating_count": ratings.get(cid, (None, 0))[1],
            }
        )
    return result


async def team_analytics(
    db: AsyncSession, competition: Competition, *, live: bool = False
) -> list[dict[str, Any]]:
    """Per-subject standing (rank/points/last solve from the scoreboard) plus a
    distinct-challenge solve count, first-blood count, and tickets opened — the
    "team progress" view.

    ``live=True`` reads the scoreboard past a freeze (§13) — the organiser view;
    the post-event report uses it so a lingering freeze can't hide final
    standings. The default (freeze-aware) preserves the analytics endpoint's
    behaviour."""
    from models.ticket import Ticket

    team_mode = competition.participation_mode == "team"
    subject_col = Submission.team_id if team_mode else Submission.user_id
    board = await compute_scoreboard(db, competition, live=live)

    solve_rows = (
        await db.execute(
            select(subject_col, func.count(distinct(Submission.challenge_id)))
            .where(Submission.competition_id == competition.id, *_AWARDED)
            .group_by(subject_col)
        )
    ).all()
    solves_by_subject = {sid: count for sid, count in solve_rows}

    # First blood = the earliest awarded submission per challenge. Fetch awarded
    # solves oldest-first and take the first subject seen for each challenge.
    firstblood_rows = (
        await db.execute(
            select(subject_col, Submission.challenge_id, Submission.created_at)
            .where(Submission.competition_id == competition.id, *_AWARDED)
            .order_by(Submission.created_at, Submission.id)
        )
    ).all()
    first_solver: dict[str, str] = {}
    for subject_id, challenge_id, _created in firstblood_rows:
        first_solver.setdefault(challenge_id, subject_id)
    first_bloods: dict[str, int] = {}
    for subject_id in first_solver.values():
        first_bloods[subject_id] = first_bloods.get(subject_id, 0) + 1

    # Tickets opened, credited to the subject: the opener's team (team mode) or
    # the opener (individual mode). A team-mode ticket from a teamless opener has
    # a null team_id and simply isn't counted against any team.
    ticket_subject_col = Ticket.team_id if team_mode else Ticket.opener_user_id
    ticket_rows = (
        await db.execute(
            select(ticket_subject_col, func.count(Ticket.id))
            .where(
                Ticket.competition_id == competition.id,
                ticket_subject_col.is_not(None),
            )
            .group_by(ticket_subject_col)
        )
    ).all()
    tickets_by_subject = {sid: count for sid, count in ticket_rows}

    return [
        {
            "subject_id": entry["subject_id"],
            "name": entry["name"],
            "rank": entry["rank"],
            "points": entry["points"],
            "solve_count": solves_by_subject.get(entry["subject_id"], 0),
            "first_bloods": first_bloods.get(entry["subject_id"], 0),
            "ticket_count": tickets_by_subject.get(entry["subject_id"], 0),
            "last_solve_at": entry["last_solve_at"],
        }
        for entry in board["entries"]
    ]
