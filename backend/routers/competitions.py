"""Competition routes (ARCHITECTURE.md §6, §13.1).

Tier 0 scope is the *entity + scoping foundation* (ROADMAP #2): create a
competition (to exercise RBAC + the event bus) and read them back. Full
competition management — editing name/schedule, registration windows,
public/private visibility — is Tier 1 #6 and is deliberately not built here.

The competition is the tenancy *root*, so it isn't itself competition-scoped;
the §6.2 discipline (every tenant-scoped query filtered by ``competition_id``)
applies to the child entities that hang off it, which arrive in Tier 1. That
discipline is carried by ``CompetitionScopedMixin`` (db.py) so it's structural
rather than per-endpoint memory.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user, require_permission
from db import get_db
from models.competition import Competition
from models.user import User
from schemas.competition import (
    CompetitionCreate,
    CompetitionOut,
    CompetitionUpdate,
)
from utils.event_bus import event_bus

router = APIRouter(prefix="/api/competitions", tags=["competitions"])


@router.get("", response_model=list[CompetitionOut])
async def list_competitions(
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Competition]:
    result = await db.execute(select(Competition).order_by(Competition.created_at))
    return list(result.scalars().all())


@router.get("/{competition_id}", response_model=CompetitionOut)
async def get_competition(
    competition_id: str,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return competition


@router.post("", response_model=CompetitionOut, status_code=status.HTTP_201_CREATED)
async def create_competition(
    body: CompetitionCreate,
    # create_competition is a global-scope permission (§7.1) — held by
    # Administrator, not a per-competition role.
    current_user: User = Depends(require_permission("create_competition")),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    competition = Competition(
        name=body.name,
        description=body.description,
        start_at=body.start_at,
        end_at=body.end_at,
        registration_opens_at=body.registration_opens_at,
        registration_closes_at=body.registration_closes_at,
        participation_mode=body.participation_mode,
        visibility=body.visibility,
    )
    db.add(competition)
    await db.commit()
    await db.refresh(competition)

    await event_bus.emit(
        "competition.created",
        {
            "competition_id": competition.id,
            "user_id": current_user.id,
            "name": competition.name,
        },
    )
    return competition


@router.patch("/{competition_id}", response_model=CompetitionOut)
async def update_competition(
    competition_id: str,
    body: CompetitionUpdate,
    # edit_competition is competition-scoped (§7.1). require_permission resolves
    # the competition from the {competition_id} path param; a global Administrator
    # satisfies it for any competition, a Judge only for their own (§7.5).
    current_user: User = Depends(require_permission("edit_competition")),
    db: AsyncSession = Depends(get_db),
) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )

    # PATCH semantics: apply only the fields the caller actually sent.
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(competition, field, value)
    await db.commit()
    await db.refresh(competition)

    await event_bus.emit(
        "competition.updated",
        {
            "competition_id": competition.id,
            "user_id": current_user.id,
            "changed_fields": sorted(changes.keys()),
        },
    )
    return competition
