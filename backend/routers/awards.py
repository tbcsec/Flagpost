"""Manual awards (§5.3 — judges granting titled, point-bearing recognition).

The manual counterpart to the automation engine's ``create_award`` action: a
judge selects competitors from the individual-mode roster and hands them an
award (title + description + points). Each award is an ``Achievement`` row whose
``points`` fold into the scoreboard exactly like a ``ScoreAdjustment`` (see
``utils/scoreboard``), and emits ``achievement.awarded`` so audit + any
automation rules watching awards behave identically to an engine-granted one.

Nested under ``/api/competitions/{competition_id}/awards`` so every query is
scoped by ``competition_id`` (§6.2). Gated on ``score_override`` — the same
capability that governs manual scoring overrides. Targets must hold the
competition-scoped Participant role (§7.5): awards are for competitors.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.automation import Achievement
from models.competition import Competition
from models.role import Role, RoleAssignment
from models.user import User
from schemas.award import AwardCreate, AwardOut
from utils.event_bus import event_bus

router = APIRouter(
    prefix="/api/competitions/{competition_id}/awards", tags=["awards"]
)


@router.post("", response_model=list[AwardOut], status_code=status.HTTP_201_CREATED)
async def create_awards(
    competition_id: str,
    body: AwardCreate,
    actor: User = Depends(require_permission("score_override")),
    db: AsyncSession = Depends(get_db),
) -> list[AwardOut]:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )

    # Manual awards are user-scoped (team_id=None). In a team-mode competition the
    # scoreboard credits the *team* subject, so a user-scoped award's points would
    # silently never show — reject rather than grant invisible points. (The UI only
    # surfaces this on the individual-mode roster; automation's create_award, which
    # can credit a team, is the team-mode path.)
    if competition.participation_mode == "team":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Manual awards are only available in individual-mode competitions",
        )

    # Only competitors in *this* competition can be awarded (§6.2/§7.5).
    participant_ids = set(
        (
            await db.execute(
                select(RoleAssignment.user_id)
                .join(Role, Role.id == RoleAssignment.role_id)
                .where(
                    RoleAssignment.competition_id == competition_id,
                    Role.name == "Participant",
                )
            )
        )
        .scalars()
        .all()
    )
    requested = list(dict.fromkeys(body.user_ids))  # de-dupe, keep order
    invalid = [uid for uid in requested if uid not in participant_ids]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more recipients are not competitors in this competition",
        )

    awards = [
        Achievement(
            competition_id=competition_id,
            title=body.title,
            description=body.description,
            points=body.points,
            user_id=uid,
            team_id=None,  # individual-mode roster → user-scoped award
            awarded_by_user_id=actor.id,
        )
        for uid in requested
    ]
    db.add_all(awards)
    await db.commit()

    for award in awards:
        await event_bus.emit(
            "achievement.awarded",
            {
                "competition_id": competition_id,
                "user_id": award.user_id,
                "team_id": None,
                "title": award.title,
                "points": award.points,
                "awarded_by_user_id": actor.id,
            },
        )

    return [AwardOut.model_validate(a) for a in awards]
