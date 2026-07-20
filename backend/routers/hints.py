"""Hint routes (ROADMAP #15, §11.3).

Nested under a challenge. Authoring (create/delete) gates on ``challenge_edit``
— a hint is challenge content, so its mutations reuse the challenge's edit
permission and emit ``challenge.updated`` (the challenge's hint set changed)
rather than inventing a new event. Revealing gates on ``challenge_view`` and is
the competitor action: idempotent per subject (reveal once, pay once), it
records a ``HintReveal`` and emits ``challenge.hint_requested`` (§3.2).

Body confidentiality: a competitor only ever receives a hint's text once their
subject has revealed it. Editors (``challenge_edit``) see every body, unrevealed
or not, so they can author.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission, user_has_permission
from db import get_db
from models.competition import Competition
from models.hint import Hint, HintReveal
from models.user import User
from routers.challenges import load_visible_challenge
from schemas.hint import HintCreate, HintOut, HintRevealOut
from utils.event_bus import event_bus
from utils.scoring import resolve_subject, revealed_hint_ids, subject_has_revealed

router = APIRouter(
    prefix="/api/competitions/{competition_id}/challenges/{challenge_id}/hints",
    tags=["hints"],
)


async def _get_scoped_hint(
    db: AsyncSession, competition_id: str, challenge_id: str, hint_id: str
) -> Hint:
    hint = await db.scalar(
        select(Hint).where(
            Hint.id == hint_id,
            Hint.competition_id == competition_id,
            Hint.challenge_id == challenge_id,
        )
    )
    if hint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hint not found"
        )
    return hint


@router.get("", response_model=list[HintRevealOut])
async def list_hints(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[HintRevealOut]:
    # 404s a draft for a non-editor, exactly like the challenge read (§13.2).
    await load_visible_challenge(db, competition_id, challenge_id, current_user)

    hints = list(
        (
            await db.execute(
                select(Hint)
                .where(
                    Hint.competition_id == competition_id,
                    Hint.challenge_id == challenge_id,
                )
                .order_by(Hint.created_at)
            )
        ).scalars()
    )

    is_editor = await user_has_permission(
        db, current_user.id, "challenge_edit", competition_id
    )
    if is_editor:
        # Authors see every body regardless of reveal state.
        return [
            HintRevealOut(
                id=h.id,
                challenge_id=h.challenge_id,
                cost=h.cost,
                revealed=True,
                body=h.body,
            )
            for h in hints
        ]

    competition = await db.get(Competition, competition_id)
    subject = (
        await resolve_subject(db, competition, current_user)
        if competition is not None
        else None
    )
    revealed = (
        await revealed_hint_ids(db, challenge_id, subject)
        if subject is not None
        else set()
    )
    return [
        HintRevealOut(
            id=h.id,
            challenge_id=h.challenge_id,
            cost=h.cost,
            revealed=h.id in revealed,
            body=h.body if h.id in revealed else None,
        )
        for h in hints
    ]


@router.post("", response_model=HintOut, status_code=status.HTTP_201_CREATED)
async def create_hint(
    competition_id: str,
    challenge_id: str,
    body: HintCreate,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
) -> Hint:
    # An editor can author on any challenge they can see, drafts included.
    await load_visible_challenge(db, competition_id, challenge_id, current_user)
    hint = Hint(
        competition_id=competition_id,
        challenge_id=challenge_id,
        body=body.body,
        cost=body.cost,
    )
    db.add(hint)
    await db.commit()
    await db.refresh(hint)
    await event_bus.emit(
        "challenge.updated",
        {"competition_id": competition_id, "challenge_id": challenge_id},
    )
    return hint


@router.delete("/{hint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hint(
    competition_id: str,
    challenge_id: str,
    hint_id: str,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
) -> None:
    hint = await _get_scoped_hint(db, competition_id, challenge_id, hint_id)
    await db.delete(hint)
    await db.commit()
    await event_bus.emit(
        "challenge.updated",
        {"competition_id": competition_id, "challenge_id": challenge_id},
    )


@router.post("/{hint_id}/reveal", response_model=HintRevealOut)
async def reveal_hint(
    competition_id: str,
    challenge_id: str,
    hint_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> HintRevealOut:
    await load_visible_challenge(db, competition_id, challenge_id, current_user)
    hint = await _get_scoped_hint(db, competition_id, challenge_id, hint_id)

    competition = await db.get(Competition, competition_id)
    subject = await resolve_subject(db, competition, current_user)
    if subject is None:
        # Team-mode competitor with no team — nothing to attribute the reveal to.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Join a team before revealing hints",
        )

    # Idempotent: an already-revealed hint returns its body without charging
    # again (the cost is per subject, not per click).
    if await subject_has_revealed(db, hint_id, subject):
        return HintRevealOut(
            id=hint.id,
            challenge_id=hint.challenge_id,
            cost=hint.cost,
            revealed=True,
            body=hint.body,
        )

    db.add(
        HintReveal(
            competition_id=competition_id,
            hint_id=hint_id,
            challenge_id=challenge_id,
            user_id=current_user.id,
            team_id=subject.team_id,
            cost_charged=hint.cost,
        )
    )
    await db.commit()

    await event_bus.emit(
        "challenge.hint_requested",
        {
            "competition_id": competition_id,
            "challenge_id": challenge_id,
            "hint_id": hint_id,
            "user_id": current_user.id,
            "team_id": subject.team_id,
            "cost": hint.cost,
        },
    )
    return HintRevealOut(
        id=hint.id,
        challenge_id=hint.challenge_id,
        cost=hint.cost,
        revealed=True,
        body=hint.body,
    )
