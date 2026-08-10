"""Scoreboard REST endpoint (ROADMAP #13) — the initial load.

Live updates ride the WebSocket room (``/ws/scoreboard/<competition_id>``,
§4.1); this route serves the same payload for first paint and for clients
without a socket. Gated on ``challenge_view`` (§7.1 — viewing the board is
part of competitor access, per the Participant role description in §7.3), and
competition-scoped like every other route (§6.2).

Scoreboard **freeze** (§13, Phase 9): a ``scoreboard_freeze`` holder can freeze
the public board at a chosen instant (default now); everyone then sees the
standings as of that time until it's lifted. Staff can still read the live board
with ``?live=true``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission, user_has_permission
from db import get_db, utcnow
from models.competition import Competition
from models.user import User
from schemas.scoreboard import FreezeRequest, ScoreboardOut
from utils.event_bus import event_bus
from utils.scoreboard import cached_scoreboard, compute_scoreboard

router = APIRouter(
    prefix="/api/competitions/{competition_id}/scoreboard", tags=["scoreboard"]
)


async def _get_competition(db: AsyncSession, competition_id: str) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return competition


@router.get("", response_model=ScoreboardOut)
async def get_scoreboard(
    competition_id: str,
    live: bool = False,
    bracket: str | None = None,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    competition = await _get_competition(db, competition_id)
    # Only a freeze-manager may bypass the freeze to see live standings.
    allow_live = live and await user_has_permission(
        db, current_user.id, "scoreboard_freeze", competition_id
    )
    # Cached read model (#87): repeated reads collapse to one compute per window.
    return await cached_scoreboard(
        db, competition, live=allow_live, bracket=bracket or None
    )


@router.post("/freeze", response_model=ScoreboardOut)
async def freeze_scoreboard(
    competition_id: str,
    body: FreezeRequest,
    current_user: User = Depends(require_permission("scoreboard_freeze")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    competition = await _get_competition(db, competition_id)
    competition.scoreboard_frozen_at = body.frozen_at or utcnow()
    await db.commit()
    await event_bus.emit(
        "scoreboard.frozen",
        {
            "competition_id": competition_id,
            "frozen_at": competition.scoreboard_frozen_at.isoformat(),
            "user_id": current_user.id,
        },
    )
    return await compute_scoreboard(db, competition, live=True)


@router.post("/unfreeze", response_model=ScoreboardOut)
async def unfreeze_scoreboard(
    competition_id: str,
    current_user: User = Depends(require_permission("scoreboard_freeze")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    competition = await _get_competition(db, competition_id)
    competition.scoreboard_frozen_at = None
    await db.commit()
    await event_bus.emit(
        "scoreboard.unfrozen",
        {"competition_id": competition_id, "user_id": current_user.id},
    )
    return await compute_scoreboard(db, competition, live=True)
