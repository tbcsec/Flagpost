"""Bracket selection (Phase 9, Group C) — a competitor picks their division.

Self-select: the acting subject (their team in team-mode, themselves in
individual-mode, via ``resolve_subject``) chooses one of the competition's
brackets. Staff (``team_view_all``) can override any subject's bracket. Mounted
under ``/api/competitions/{competition_id}/bracket`` so it's competition-scoped.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.competition import Competition
from models.user import User
from schemas.bracket import BracketOut, BracketSet, BracketSetForSubject
from utils.brackets import set_bracket
from utils.scoring import resolve_subject

router = APIRouter(
    prefix="/api/competitions/{competition_id}/bracket", tags=["brackets"]
)


async def _get_competition(db: AsyncSession, competition_id: str) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return competition


@router.get("", response_model=BracketOut)
async def get_my_bracket(
    competition_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> BracketOut:
    competition = await _get_competition(db, competition_id)
    subject = await resolve_subject(db, competition, current_user)
    if subject is None:
        return BracketOut(bracket=None)
    from utils.brackets import brackets_by_subject

    picks = await brackets_by_subject(db, competition_id)
    return BracketOut(bracket=picks.get(subject.id))


@router.put("", response_model=BracketOut)
async def set_my_bracket(
    competition_id: str,
    body: BracketSet,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> BracketOut:
    competition = await _get_competition(db, competition_id)
    subject = await resolve_subject(db, competition, current_user)
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Join a team before choosing a bracket",
        )
    await set_bracket(db, competition, subject.id, body.bracket)
    await db.commit()
    return BracketOut(bracket=body.bracket or None)


@router.put("/{subject_id}", response_model=BracketOut)
async def set_subject_bracket(
    competition_id: str,
    subject_id: str,
    body: BracketSetForSubject,
    current_user: User = Depends(require_permission("team_view_all")),
    db: AsyncSession = Depends(get_db),
) -> BracketOut:
    """Staff override of any subject's bracket (team id or user id)."""
    competition = await _get_competition(db, competition_id)
    await set_bracket(db, competition, subject_id, body.bracket)
    await db.commit()
    return BracketOut(bracket=body.bracket or None)
