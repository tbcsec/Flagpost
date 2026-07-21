"""Operational dashboard read endpoints (ROADMAP #16, §10).

Each widget fetches its own data (§10.1), so this is a handful of small
read-only, competition-scoped (§6.2) endpoints rather than one payload:

- ``/stats`` and ``/recent-solves`` and ``/me`` gate on ``challenge_view`` —
  competitor-level aggregates every participant's dashboard shows.
- ``/challenge-health`` exposes attempt volume (failed submissions included),
  which is operational, so it gates on ``view_competition_analytics`` (staff).

All figures are derived from the submissions data scoring already records; no
new instrumentation.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db, utcnow
from models.challenge import Challenge
from models.competition import Competition
from models.role import Role, RoleAssignment
from models.submission import Submission
from models.team import Team
from models.user import User
from schemas.dashboard import (
    ChallengeHealth,
    DashboardStats,
    MyStanding,
    RecentSolve,
)
from utils.scoreboard import compute_scoreboard
from utils.scoring import resolve_subject, solved_challenge_ids

router = APIRouter(
    prefix="/api/competitions/{competition_id}/dashboard", tags=["dashboard"]
)

_AWARDED = (Submission.is_correct.is_(True), Submission.is_duplicate.is_(False))


async def _load_competition(db: AsyncSession, competition_id: str) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return competition


@router.get("/stats", response_model=DashboardStats)
async def dashboard_stats(
    competition_id: str,
    _user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> DashboardStats:
    competition = await _load_competition(db, competition_id)

    total_submissions = await db.scalar(
        select(func.count(Submission.id)).where(
            Submission.competition_id == competition_id
        )
    )
    total_solves = await db.scalar(
        select(func.count(Submission.id)).where(
            Submission.competition_id == competition_id, *_AWARDED
        )
    )
    recent_solves_1h = await db.scalar(
        select(func.count(Submission.id)).where(
            Submission.competition_id == competition_id,
            *_AWARDED,
            Submission.created_at >= utcnow() - timedelta(hours=1),
        )
    )
    published_challenges = await db.scalar(
        select(func.count(Challenge.id)).where(
            Challenge.competition_id == competition_id,
            Challenge.state == "published",
        )
    )
    if competition.participation_mode == "team":
        active_participants = await db.scalar(
            select(func.count(Team.id)).where(Team.competition_id == competition_id)
        )
    else:
        active_participants = await db.scalar(
            select(func.count(distinct(RoleAssignment.user_id)))
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(
                RoleAssignment.competition_id == competition_id,
                Role.name == "Participant",
            )
        )

    return DashboardStats(
        total_solves=total_solves or 0,
        total_submissions=total_submissions or 0,
        active_participants=active_participants or 0,
        published_challenges=published_challenges or 0,
        recent_solves_1h=recent_solves_1h or 0,
    )


@router.get("/recent-solves", response_model=list[RecentSolve])
async def recent_solves(
    competition_id: str,
    _user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[RecentSolve]:
    competition = await _load_competition(db, competition_id)
    rows = (
        await db.execute(
            select(
                Submission.team_id,
                Submission.user_id,
                Submission.points_awarded,
                Submission.created_at,
                Challenge.title,
            )
            .join(Challenge, Challenge.id == Submission.challenge_id)
            .where(Submission.competition_id == competition_id, *_AWARDED)
            .order_by(Submission.created_at.desc())
            .limit(10)
        )
    ).all()

    # Resolve subject names in one query rather than per row.
    if competition.participation_mode == "team":
        ids = {r.team_id for r in rows if r.team_id}
        names = dict(
            (
                await db.execute(select(Team.id, Team.name).where(Team.id.in_(ids)))
            ).all()
        )
        name_for = lambda r: names.get(r.team_id, "—")  # noqa: E731
    else:
        ids = {r.user_id for r in rows}
        names = dict(
            (
                await db.execute(
                    select(User.id, User.display_name).where(User.id.in_(ids))
                )
            ).all()
        )
        name_for = lambda r: names.get(r.user_id, "—")  # noqa: E731

    return [
        RecentSolve(
            subject_name=name_for(r),
            challenge_title=r.title,
            points=r.points_awarded,
            at=r.created_at,
        )
        for r in rows
    ]


@router.get("/challenge-health", response_model=list[ChallengeHealth])
async def challenge_health(
    competition_id: str,
    _user: User = Depends(require_permission("view_competition_analytics")),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeHealth]:
    await _load_competition(db, competition_id)
    solves_sub = (
        select(
            Submission.challenge_id.label("cid"),
            func.count(Submission.id).label("solves"),
        )
        .where(Submission.competition_id == competition_id, *_AWARDED)
        .group_by(Submission.challenge_id)
        .subquery()
    )
    attempts_sub = (
        select(
            Submission.challenge_id.label("cid"),
            func.count(Submission.id).label("attempts"),
        )
        .where(Submission.competition_id == competition_id)
        .group_by(Submission.challenge_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                Challenge.id,
                Challenge.title,
                Challenge.points,
                solves_sub.c.solves,
                attempts_sub.c.attempts,
            )
            .outerjoin(solves_sub, solves_sub.c.cid == Challenge.id)
            .outerjoin(attempts_sub, attempts_sub.c.cid == Challenge.id)
            .where(Challenge.competition_id == competition_id)
            .order_by(Challenge.created_at)
        )
    ).all()
    return [
        ChallengeHealth(
            challenge_id=cid,
            title=title,
            points=points,
            solves=solves or 0,
            attempts=attempts or 0,
        )
        for cid, title, points, solves, attempts in rows
    ]


@router.get("/me", response_model=MyStanding)
async def my_standing(
    competition_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> MyStanding:
    competition = await _load_competition(db, competition_id)
    subject = await resolve_subject(db, competition, current_user)
    if subject is None:
        # A viewer with no scoring subject (e.g. team-mode without a team).
        return MyStanding(rank=None, points=None, solved_count=0)

    board = await compute_scoreboard(db, competition)
    entry = next(
        (e for e in board["entries"] if e["subject_id"] == subject.id), None
    )
    solved = await solved_challenge_ids(db, competition_id, subject)
    return MyStanding(
        rank=entry["rank"] if entry else None,
        points=entry["points"] if entry else 0,
        solved_count=len(solved),
    )
