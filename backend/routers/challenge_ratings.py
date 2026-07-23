"""Challenge ratings (Phase 9) — an extension of the feedback module.

After solving a challenge, a competitor may rate it 1–5; staff read per-challenge
aggregates to see which challenges landed well. Like surveys, these routes honour
the feedback module's per-competition toggle (§11.3); on top of that, the rating
prompt is only active when the competition's ``challenge_ratings_enabled`` flag is
on (a separate per-competition switch). Only a competitor who has *solved* the
challenge may rate it, once (re-rating updates the value).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.challenge import Challenge
from models.competition import Competition
from models.feedback import ChallengeRating
from models.user import User
from plugins.loader import is_module_enabled
from routers.challenges import load_visible_challenge
from schemas.feedback import ChallengeRatingRequest, ChallengeRatingSummary
from utils.event_bus import event_bus
from utils.scoring import resolve_subject, subject_has_solved

router = APIRouter(
    prefix="/api/competitions/{competition_id}/challenge-ratings", tags=["feedback"]
)


async def _guard(db: AsyncSession, competition_id: str) -> Competition:
    """The competition exists and the feedback module is enabled for it (§11.3)."""
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    if not await is_module_enabled(db, "feedback", competition_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The feedback module is disabled for this competition",
        )
    return competition


@router.post("/{challenge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def rate_challenge(
    competition_id: str,
    challenge_id: str,
    body: ChallengeRatingRequest,
    current_user: User = Depends(require_permission("feedback_submit")),
    db: AsyncSession = Depends(get_db),
) -> None:
    competition = await _guard(db, competition_id)
    if not competition.challenge_ratings_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Challenge ratings are off for this competition",
        )
    await load_visible_challenge(db, competition_id, challenge_id, current_user)

    # Only someone who solved it can rate it.
    subject = await resolve_subject(db, competition, current_user)
    if subject is None or not await subject_has_solved(db, challenge_id, subject):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solve the challenge before rating it",
        )

    existing = await db.scalar(
        select(ChallengeRating).where(
            ChallengeRating.challenge_id == challenge_id,
            ChallengeRating.user_id == current_user.id,
        )
    )
    if existing is not None:
        existing.rating = body.rating
    else:
        db.add(
            ChallengeRating(
                competition_id=competition_id,
                challenge_id=challenge_id,
                user_id=current_user.id,
                rating=body.rating,
            )
        )
    await db.commit()

    await event_bus.emit(
        "challenge.rated",
        {
            "competition_id": competition_id,
            "challenge_id": challenge_id,
            "user_id": current_user.id,
            "rating": body.rating,
        },
    )


@router.get("", response_model=list[ChallengeRatingSummary])
async def rating_summary(
    competition_id: str,
    _user: User = Depends(require_permission("feedback_view_responses")),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeRatingSummary]:
    """Per-challenge average rating + count (staff — which challenges worked well)."""
    await _guard(db, competition_id)
    rows = (
        await db.execute(
            select(
                Challenge.id,
                Challenge.title,
                func.avg(ChallengeRating.rating),
                func.count(ChallengeRating.id),
            )
            .join(ChallengeRating, ChallengeRating.challenge_id == Challenge.id)
            .where(Challenge.competition_id == competition_id)
            .group_by(Challenge.id, Challenge.title)
            .order_by(func.avg(ChallengeRating.rating).desc())
        )
    ).all()
    return [
        ChallengeRatingSummary(
            challenge_id=cid, title=title, average=round(float(avg), 2), count=count
        )
        for cid, title, avg, count in rows
    ]
