"""Participant roster (ROADMAP #7 — the individual-mode counterpart to teams).

Team-mode competitions browse participation through ``/teams``; individual-mode
competitions have no teams, so this per-user roster is the "who's competing"
surface. It lists everyone holding the competition-scoped **Participant** role
(§7.5) with their individual standing (rank/points reused from the scoreboard so
ranking is identical) and distinct-solve count.

Nested under ``/api/competitions/{competition_id}/participants`` so every query
is scoped by ``competition_id`` (§6.2). Gated on ``challenge_view`` — the same
audience the scoreboard is visible to; it exposes names + standing only, so it's
no wider a disclosure than the board itself.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.competition import Competition
from models.role import Role, RoleAssignment
from models.submission import Submission
from models.user import User
from schemas.participant import ParticipantOut
from utils.scoreboard import compute_scoreboard

router = APIRouter(
    prefix="/api/competitions/{competition_id}/participants", tags=["participants"]
)

_AWARDED = (Submission.is_correct.is_(True), Submission.is_duplicate.is_(False))


@router.get("", response_model=list[ParticipantOut])
async def list_participants(
    competition_id: str,
    _user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[ParticipantOut]:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )

    # The roster: every distinct Participant-role holder in this competition,
    # with when they joined (the role assignment's created_at).
    roster = (
        await db.execute(
            select(User.id, User.display_name, RoleAssignment.created_at)
            .join(RoleAssignment, RoleAssignment.user_id == User.id)
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(
                RoleAssignment.competition_id == competition_id,
                Role.name == "Participant",
            )
            .distinct()
        )
    ).all()

    # Standing from the same scoreboard computation (individual mode → each entry's
    # subject_id is the user id), so rank/points match the board exactly.
    board = await compute_scoreboard(db, competition)
    standing = {e["subject_id"]: (e["rank"], e["points"]) for e in board["entries"]}

    # Distinct challenges each user has solved.
    solve_rows = (
        await db.execute(
            select(
                Submission.user_id,
                func.count(distinct(Submission.challenge_id)),
            )
            .where(Submission.competition_id == competition_id, *_AWARDED)
            .group_by(Submission.user_id)
        )
    ).all()
    solves = {user_id: count for user_id, count in solve_rows}

    participants = [
        ParticipantOut(
            user_id=user_id,
            display_name=display_name,
            joined_at=joined_at,
            rank=standing.get(user_id, (None, 0))[0],
            points=standing.get(user_id, (None, 0))[1],
            solve_count=solves.get(user_id, 0),
        )
        for user_id, display_name, joined_at in roster
    ]
    # Ranked first (scored participants by rank), then the unscored alphabetically.
    participants.sort(
        key=lambda p: (p.rank is None, p.rank or 0, p.display_name.lower())
    )
    return participants
