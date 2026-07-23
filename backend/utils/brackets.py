"""Bracket selection helpers (Phase 9, Group C).

A subject (team or user) self-selects one of the competition's brackets at join.
The choice validates against the competition's managed ``brackets`` list and is
stored keyed by the scoring subject id, so ``utils/scoreboard`` can label and
filter each entry by division.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.bracket import BracketMembership
from models.competition import Competition


async def set_bracket(
    db: AsyncSession, competition: Competition, subject_id: str, bracket: str | None
) -> None:
    """Upsert a subject's bracket choice, validated against the competition's
    managed list. ``None``/blank clears any existing choice."""
    valid = set(competition.brackets or [])
    existing = await db.scalar(
        select(BracketMembership).where(
            BracketMembership.competition_id == competition.id,
            BracketMembership.subject_id == subject_id,
        )
    )
    if not bracket:
        if existing is not None:
            await db.delete(existing)
        return
    if bracket not in valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown bracket for this competition",
        )
    if existing is None:
        db.add(
            BracketMembership(
                competition_id=competition.id, subject_id=subject_id, bracket=bracket
            )
        )
    else:
        existing.bracket = bracket


async def brackets_by_subject(
    db: AsyncSession, competition_id: str
) -> dict[str, str]:
    """subject_id -> chosen bracket, for a whole competition (scoreboard label)."""
    rows = (
        await db.execute(
            select(BracketMembership.subject_id, BracketMembership.bracket).where(
                BracketMembership.competition_id == competition_id
            )
        )
    ).all()
    return {sid: b for sid, b in rows}
