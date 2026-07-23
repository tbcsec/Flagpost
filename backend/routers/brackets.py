"""Bracket assignment (Phase 9, Group C) — staff place competitors in divisions.

Brackets are **staff-assigned** (not competitor self-select): an ``edit_competition``
holder (admin/judge, competition-scoped) sets a subject's division. The subject
is the team (team-mode) or the user (individual-mode) — the §13.2 scoring
subject. Mounted under ``/api/competitions/{competition_id}/bracket``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.competition import Competition
from models.user import User
from schemas.bracket import BracketOut, BracketSetForSubject
from utils.brackets import set_bracket

router = APIRouter(
    prefix="/api/competitions/{competition_id}/bracket", tags=["brackets"]
)


@router.put("/{subject_id}", response_model=BracketOut)
async def set_subject_bracket(
    competition_id: str,
    subject_id: str,
    body: BracketSetForSubject,
    current_user: User = Depends(require_permission("edit_competition")),
    db: AsyncSession = Depends(get_db),
) -> BracketOut:
    """Assign a subject's bracket (team id or user id). Admin/judge only."""
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    await set_bracket(db, competition, subject_id, body.bracket)
    await db.commit()
    return BracketOut(bracket=body.bracket or None)
