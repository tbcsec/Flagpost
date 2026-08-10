"""Public (spectator) scoreboard — the one unauthenticated read (Phase 9).

When an organiser opts a competition in (``public_scoreboard``), its standings
are listed on ``/public`` and viewable without an account, for streamers,
spectators and sponsors. Anything not opted-in (or archived) 404s so it isn't
disclosed. The board respects a scoreboard freeze exactly like the competitor
view (a spectator is a non-staff viewer). The **CTFtime feed** is a separate
opt-in (``ctftime_enabled``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.competition import Competition
from schemas.scoreboard import (
    PublicActivityOut,
    PublicCompetitionOut,
    PublicInsightsOut,
    PublicScoreboardOut,
)
from utils.public_insights import public_insights, recent_activity
from utils.scoreboard import cached_scoreboard

router = APIRouter(prefix="/api/public", tags=["public"])


async def _load_public_competition(db: AsyncSession, competition_id: str) -> Competition:
    """The competition behind a spectator route, or 404. A competition that
    hasn't opted into a public board (or has been archived) is never disclosed —
    the 404 is identical to one that doesn't exist."""
    competition = await db.get(Competition, competition_id)
    if (
        competition is None
        or not competition.public_scoreboard
        or competition.archived_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Scoreboard not found"
        )
    return competition


@router.get("/competitions", response_model=list[PublicCompetitionOut])
async def public_competitions(db: AsyncSession = Depends(get_db)) -> list:
    """The competitions offering a public scoreboard — the /public directory."""
    rows = (
        await db.execute(
            select(Competition)
            .where(
                Competition.public_scoreboard.is_(True),
                Competition.archived_at.is_(None),
            )
            .order_by(Competition.start_at.is_(None), Competition.start_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "participation_mode": c.participation_mode,
            "start_at": c.start_at,
            "end_at": c.end_at,
        }
        for c in rows
    ]


@router.get(
    "/competitions/{competition_id}/scoreboard",
    response_model=PublicScoreboardOut,
)
async def public_scoreboard(
    competition_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    competition = await _load_public_competition(db, competition_id)
    board = await cached_scoreboard(db, competition)  # spectator = non-staff
    return {
        **board,
        "name": competition.name,
        "start_at": competition.start_at,
        "end_at": competition.end_at,
    }


@router.get(
    "/competitions/{competition_id}/insights",
    response_model=PublicInsightsOut,
)
async def public_competition_insights(
    competition_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """Spectator context for the public page (#24): headline stats, standout
    challenges/competitors, and a cumulative points timeline for the top
    entrants. Freeze-aware exactly like the board it accompanies — see
    ``utils/public_insights``. Same opt-in gating as the scoreboard."""
    competition = await _load_public_competition(db, competition_id)
    return await public_insights(db, competition)


@router.get(
    "/competitions/{competition_id}/activity",
    response_model=PublicActivityOut,
)
async def public_competition_activity(
    competition_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """Recent awarded solves, each tagged first-blood — the feed venue mode
    (#77) polls to drive its first-blood splash. Freeze-aware and under the same
    opt-in/archived gating as the board it accompanies (see ``recent_activity``)."""
    competition = await _load_public_competition(db, competition_id)
    return await recent_activity(db, competition)


@router.get("/competitions/{competition_id}/ctftime")
async def ctftime_feed(
    competition_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """The [CTFtime scoreboard feed](https://ctftime.org/json-scoreboard-feed):
    ``{"standings": [{"pos", "team", "score"}, ...]}``. An organiser pastes this
    URL into CTFtime so a public event can be rated. Opt-in per competition
    (``ctftime_enabled``); respects the freeze like the spectator board."""
    competition = await db.get(Competition, competition_id)
    if (
        competition is None
        or not competition.ctftime_enabled
        or competition.archived_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found"
        )
    board = await cached_scoreboard(db, competition)
    return {
        "standings": [
            {"pos": e["rank"], "team": e["name"], "score": e["points"]}
            for e in board["entries"]
        ]
    }
