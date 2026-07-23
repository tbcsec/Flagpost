"""Public (spectator) scoreboard — the one unauthenticated read (Phase 9).

A ``public`` competition's standings are viewable without an account, for
streamers, spectators and sponsors. Only public, non-archived competitions are
exposed; anything else 404s so a private competition's existence isn't
disclosed. The board respects a scoreboard freeze exactly like the competitor
view (a spectator is a non-staff viewer), so freezing hides the final stretch
from the public too.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.competition import Competition
from schemas.scoreboard import PublicScoreboardOut
from utils.scoreboard import compute_scoreboard

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get(
    "/competitions/{competition_id}/scoreboard",
    response_model=PublicScoreboardOut,
)
async def public_scoreboard(
    competition_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    competition = await db.get(Competition, competition_id)
    if (
        competition is None
        or competition.visibility != "public"
        or competition.archived_at is not None
    ):
        # Don't disclose that a private/archived competition exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Scoreboard not found"
        )
    board = await compute_scoreboard(db, competition)  # spectator = non-staff
    return {
        **board,
        "name": competition.name,
        "start_at": competition.start_at,
        "end_at": competition.end_at,
    }
