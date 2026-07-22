"""Analytics routes (ROADMAP #23) — read-only challenge & team reporting.

Competition-scoped (§6.2) and gated on ``view_competition_analytics`` (§7.1) —
staff-only (Judge holds it, Participant doesn't). The figures come from
``utils/analytics`` off already-recorded submission/hint/ticket data.

The ``analytics`` module is optional (§11.3), so the endpoints 404 when it's
disabled for the competition — the per-request enable gate, same as
automations/feedback.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.competition import Competition
from models.user import User
from plugins.loader import is_module_enabled
from schemas.analytics import (
    ChallengeAnalyticsOut,
    TeamAnalyticsOut,
)
from utils.analytics import challenge_analytics, subject_count, team_analytics

router = APIRouter(
    prefix="/api/competitions/{competition_id}/analytics", tags=["analytics"]
)


async def _competition_or_404(
    db: AsyncSession, competition_id: str
) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    if not await is_module_enabled(db, "analytics", competition_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The analytics module is disabled for this competition",
        )
    return competition


@router.get("/challenges", response_model=ChallengeAnalyticsOut)
async def challenge_report(
    competition_id: str,
    _user: User = Depends(require_permission("view_competition_analytics")),
    db: AsyncSession = Depends(get_db),
) -> ChallengeAnalyticsOut:
    competition = await _competition_or_404(db, competition_id)
    return ChallengeAnalyticsOut(
        mode=competition.participation_mode,
        subject_count=await subject_count(db, competition),
        challenges=await challenge_analytics(db, competition),
    )


@router.get("/teams", response_model=TeamAnalyticsOut)
async def team_report(
    competition_id: str,
    _user: User = Depends(require_permission("view_competition_analytics")),
    db: AsyncSession = Depends(get_db),
) -> TeamAnalyticsOut:
    competition = await _competition_or_404(db, competition_id)
    return TeamAnalyticsOut(
        mode=competition.participation_mode,
        teams=await team_analytics(db, competition),
    )
