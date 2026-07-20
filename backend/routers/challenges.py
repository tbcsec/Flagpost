"""Challenge routes (ROADMAP #8) — admin authoring surface for Tier 1.

Scoping and access (§6.2, §7.6):
- Everything is nested under the competition path; every query filters on it.
- Reads gate on ``challenge_view``; drafts are visible only to users who also
  hold ``challenge_edit`` (a viewer-only role sees published challenges, which
  is exactly what the Phase 6 competitor surface will rely on).
- Writes gate on the §7.1 challenge permissions (create/edit/delete/publish).

Flag handling (§13.2): plaintext flags arrive on create/update, are hashed
(static, salted) or stored as a pattern (regex) via utils/flags.py, and no
response ever carries anything but ``has_flag``. Publishing requires a flag —
an unsolvable published challenge is a configuration error, caught here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission, user_has_permission
from db import get_db
from models.attachment import Attachment
from models.challenge import Category, Challenge
from models.competition import Competition
from models.submission import Submission
from models.user import User
from schemas.challenge import ChallengeCreate, ChallengeOut, ChallengeUpdate
from storage import get_storage
from storage.base import ObjectStorage
from utils.event_bus import event_bus
from utils.flags import hash_static_flag, make_salt
from utils.scoring import (
    resolve_subject,
    solve_counts,
    solved_challenge_ids,
    subject_has_solved,
)

router = APIRouter(
    prefix="/api/competitions/{competition_id}/challenges", tags=["challenges"]
)


def _apply_flag(challenge: Challenge, raw_flag: str) -> None:
    """Store ``raw_flag`` according to the challenge's flag_type (§13.2)."""
    if challenge.flag_type == "regex":
        challenge.flag_regex = raw_flag
        challenge.flag_hash = None
        challenge.flag_salt = None
    else:
        salt = make_salt()
        challenge.flag_salt = salt
        challenge.flag_hash = hash_static_flag(
            raw_flag, salt, challenge.case_insensitive
        )
        challenge.flag_regex = None


async def _get_scoped_challenge(
    db: AsyncSession, competition_id: str, challenge_id: str
) -> Challenge:
    challenge = await db.scalar(
        select(Challenge).where(
            Challenge.competition_id == competition_id,
            Challenge.id == challenge_id,
        )
    )
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found"
        )
    return challenge


async def load_visible_challenge(
    db: AsyncSession, competition_id: str, challenge_id: str, user: User
) -> Challenge:
    """Return a scoped challenge, hiding drafts from non-editors (a draft 404s,
    indistinguishable from missing). Shared by challenge and attachment reads."""
    challenge = await _get_scoped_challenge(db, competition_id, challenge_id)
    if challenge.state != "published" and not await user_has_permission(
        db, user.id, "challenge_edit", competition_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found"
        )
    return challenge


async def _validate_category(
    db: AsyncSession, competition_id: str, category_id: str | None
) -> None:
    if category_id is None:
        return
    category = await db.scalar(
        select(Category).where(
            Category.competition_id == competition_id, Category.id == category_id
        )
    )
    if category is None:
        # Also rejects a category id smuggled in from another competition (§6.2).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown category for this competition",
        )


@router.get("", response_model=list[ChallengeOut])
async def list_challenges(
    competition_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[Challenge]:
    can_edit = await user_has_permission(
        db, current_user.id, "challenge_edit", competition_id
    )
    query = select(Challenge).where(Challenge.competition_id == competition_id)
    if not can_edit:
        query = query.where(Challenge.state == "published")
    result = await db.execute(query.order_by(Challenge.created_at))
    challenges = list(result.scalars().all())

    # Annotate each with solve state (Phase 6): total solves, plus whether the
    # requesting subject has solved it. A viewer with no subject (e.g. a manager
    # not on a team) simply sees solved=False everywhere.
    competition = await db.get(Competition, competition_id)
    subject = (
        await resolve_subject(db, competition, current_user)
        if competition is not None
        else None
    )
    counts = await solve_counts(db, competition_id)
    solved = (
        await solved_challenge_ids(db, competition_id, subject)
        if subject is not None
        else set()
    )
    for challenge in challenges:
        challenge.solve_count = counts.get(challenge.id, 0)
        challenge.solved = challenge.id in solved
    return challenges


@router.get("/{challenge_id}", response_model=ChallengeOut)
async def get_challenge(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> Challenge:
    challenge = await load_visible_challenge(
        db, competition_id, challenge_id, current_user
    )
    challenge.solve_count = (
        await db.scalar(
            select(func.count(Submission.id)).where(
                Submission.challenge_id == challenge_id,
                Submission.is_correct.is_(True),
                Submission.is_duplicate.is_(False),
            )
        )
    ) or 0
    competition = await db.get(Competition, competition_id)
    subject = (
        await resolve_subject(db, competition, current_user)
        if competition is not None
        else None
    )
    challenge.solved = (
        await subject_has_solved(db, challenge_id, subject)
        if subject is not None
        else False
    )
    return challenge


@router.post("", response_model=ChallengeOut, status_code=status.HTTP_201_CREATED)
async def create_challenge(
    competition_id: str,
    body: ChallengeCreate,
    current_user: User = Depends(require_permission("challenge_create")),
    db: AsyncSession = Depends(get_db),
) -> Challenge:
    await _validate_category(db, competition_id, body.category_id)

    challenge = Challenge(
        competition_id=competition_id,
        title=body.title,
        description=body.description,
        category_id=body.category_id,
        points=body.points,
        flag_type=body.flag_type,
        case_insensitive=body.case_insensitive,
    )
    if body.flag is not None:
        _apply_flag(challenge, body.flag)
    db.add(challenge)
    await db.commit()

    await event_bus.emit(
        "challenge.created",
        {
            "competition_id": competition_id,
            "challenge_id": challenge.id,
            "user_id": current_user.id,
            "title": challenge.title,
        },
    )
    return challenge


@router.patch("/{challenge_id}", response_model=ChallengeOut)
async def update_challenge(
    competition_id: str,
    challenge_id: str,
    body: ChallengeUpdate,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
) -> Challenge:
    challenge = await _get_scoped_challenge(db, competition_id, challenge_id)
    changes = body.model_dump(exclude_unset=True)
    if "category_id" in changes:
        await _validate_category(db, competition_id, changes["category_id"])

    raw_flag = changes.pop("flag", None)
    for field, value in changes.items():
        setattr(challenge, field, value)
    if raw_flag is not None:
        # Applied after flag_type/case_insensitive so a combined update hashes
        # under the *new* settings.
        _apply_flag(challenge, raw_flag)
    elif "case_insensitive" in changes or "flag_type" in changes:
        # Changing how a flag is interpreted without re-supplying it would
        # silently desync the stored hash from the new settings.
        if challenge.has_flag:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Changing flag settings requires re-entering the flag",
            )

    await db.commit()

    await event_bus.emit(
        "challenge.updated",
        {
            "competition_id": competition_id,
            "challenge_id": challenge.id,
            "user_id": current_user.id,
            "changed_fields": sorted(
                [*changes.keys(), *(["flag"] if raw_flag is not None else [])]
            ),
        },
    )
    return challenge


@router.post("/{challenge_id}/publish", response_model=ChallengeOut)
async def publish_challenge(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_publish")),
    db: AsyncSession = Depends(get_db),
) -> Challenge:
    challenge = await _get_scoped_challenge(db, competition_id, challenge_id)
    if not challenge.has_flag:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A challenge needs a flag before it can be published",
        )
    if challenge.state != "published":
        challenge.state = "published"
        await db.commit()
        await event_bus.emit(
            "challenge.published",
            {
                "competition_id": competition_id,
                "challenge_id": challenge.id,
                "user_id": current_user.id,
                "title": challenge.title,
            },
        )
    return challenge


@router.post("/{challenge_id}/unpublish", response_model=ChallengeOut)
async def unpublish_challenge(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_publish")),
    db: AsyncSession = Depends(get_db),
) -> Challenge:
    challenge = await _get_scoped_challenge(db, competition_id, challenge_id)
    if challenge.state != "draft":
        challenge.state = "draft"
        await db.commit()
        await event_bus.emit(
            "challenge.updated",
            {
                "competition_id": competition_id,
                "challenge_id": challenge.id,
                "user_id": current_user.id,
                "changed_fields": ["state"],
            },
        )
    return challenge


@router.delete("/{challenge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_challenge(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_delete")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> None:
    challenge = await _get_scoped_challenge(db, competition_id, challenge_id)
    # Remove attachment objects first — the rows cascade, but the bucket
    # objects would otherwise be orphaned (§13.3).
    keys = (
        await db.execute(
            select(Attachment.object_key).where(
                Attachment.challenge_id == challenge_id
            )
        )
    ).scalars().all()
    for key in keys:
        storage.delete(key)

    await db.delete(challenge)
    await db.commit()

    await event_bus.emit(
        "challenge.deleted",
        {
            "competition_id": competition_id,
            "challenge_id": challenge_id,
            "user_id": current_user.id,
        },
    )
