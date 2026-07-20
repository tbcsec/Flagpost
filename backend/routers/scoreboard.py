"""Scoreboard REST endpoint (ROADMAP #13) — the initial load.

Live updates ride the WebSocket room (``/ws/scoreboard/<competition_id>``,
§4.1); this route serves the same payload for first paint and for clients
without a socket. Gated on ``challenge_view`` (§7.1 — viewing the board is
part of competitor access, per the Participant role description in §7.3), and
competition-scoped like every other route (§6.2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.competition import Competition
from models.user import User
from schemas.scoreboard import ScoreboardOut
from utils.scoreboard import compute_scoreboard

router = APIRouter(
    prefix="/api/competitions/{competition_id}/scoreboard", tags=["scoreboard"]
)


@router.get("", response_model=ScoreboardOut)
async def get_scoreboard(
    competition_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return await compute_scoreboard(db, competition)
