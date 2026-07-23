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
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission, user_has_permission
from db import ensure_aware_utc, get_db, utcnow
from models.attachment import Attachment
from models.challenge import Category, Challenge
from models.competition import Competition
from models.feedback import ChallengeRating
from models.mc_guess_reset import MCGuessReset
from models.submission import Submission
from models.team import Team
from models.user import User
from schemas.challenge import (
    ChallengeCreate,
    ChallengeOut,
    ChallengeSolver,
    ChallengeUpdate,
    ResetGuessesRequest,
)
from storage import get_storage
from storage.base import ObjectStorage
from utils.event_bus import event_bus
from utils.flags import hash_static_flag, make_salt
from utils.scoring import (
    challenge_value,
    resolve_subject,
    solve_counts,
    solved_challenge_ids,
    subject_attempt_count,
    subject_attempt_counts,
    subject_has_solved,
)

router = APIRouter(
    prefix="/api/competitions/{competition_id}/challenges", tags=["challenges"]
)


def _apply_flag(challenge: Challenge, raw_flag: str) -> None:
    """Store ``raw_flag`` according to the challenge's flag_type (§13.2). For
    multiple_choice, ``raw_flag`` is the correct option — hashed like a static flag
    so the answer never leaves the server; the option list lives in ``choices``."""
    if challenge.flag_type == "regex":
        challenge.flag_regex = raw_flag
        challenge.flag_hash = None
        challenge.flag_salt = None
    else:  # static or multiple_choice — salted hash of the answer
        salt = make_salt()
        challenge.flag_salt = salt
        challenge.flag_hash = hash_static_flag(
            raw_flag, salt, challenge.case_insensitive
        )
        challenge.flag_regex = None


def _validate_multiple_choice(challenge: Challenge, raw_flag: str | None) -> None:
    """Guard the multiple_choice invariants: 2+ distinct options, and the correct
    answer (``raw_flag``) is one of them. ``raw_flag`` is None when only choices are
    being edited without re-supplying the answer — allowed, since the stored hash
    stays valid as long as the correct option remains in the (unchanged) list, but
    we can't verify a hash against the new list, so re-supplying is required when
    choices change (enforced by the caller)."""
    choices = challenge.choices or []
    cleaned = [c.strip() for c in choices]
    if len(cleaned) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A multiple-choice challenge needs at least two options",
        )
    if any(not c for c in cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Multiple-choice options can't be blank",
        )
    if len(set(cleaned)) != len(cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Multiple-choice options must be unique",
        )
    if raw_flag is not None and raw_flag.strip() not in cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The correct answer must be one of the options",
        )
    challenge.choices = cleaned


async def _set_value(db: AsyncSession, challenge: Challenge) -> None:
    """Annotate a challenge with its current worth for the response (§13.2)."""
    count = (
        await db.scalar(
            select(func.count(Submission.id)).where(
                Submission.challenge_id == challenge.id,
                Submission.is_correct.is_(True),
                Submission.is_duplicate.is_(False),
            )
        )
    ) or 0
    challenge.value = challenge_value(challenge, count)


def _prereq_ids(challenge: Challenge) -> list[str]:
    return list(challenge.prerequisites or [])


async def _validate_prerequisites(
    db: AsyncSession, competition_id: str, challenge_id: str | None, prereqs: list[str]
) -> None:
    """Prerequisites must be other challenges in the same competition (§6.2); a
    challenge can't require itself."""
    ids = [p for p in dict.fromkeys(prereqs)]  # dedupe
    if challenge_id is not None and challenge_id in ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A challenge can't be its own prerequisite",
        )
    if not ids:
        return
    found = set(
        (
            await db.execute(
                select(Challenge.id).where(
                    Challenge.competition_id == competition_id,
                    Challenge.id.in_(ids),
                )
            )
        )
        .scalars()
        .all()
    )
    if set(ids) - found:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A prerequisite is not a challenge in this competition",
        )


def _is_locked(challenge: Challenge, solved_ids: set[str]) -> bool:
    """Whether a challenge is locked for a subject: any prerequisite unsolved."""
    return any(pid not in solved_ids for pid in _prereq_ids(challenge))


def _validate_metadata(competition: Competition, challenge: Challenge) -> None:
    """Tags/difficulty must come from the competition's managed vocab (Phase 9)."""
    vocab = set(competition.challenge_tags or [])
    unknown = [t for t in (challenge.tags or []) if t not in vocab]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown tag(s) for this competition: {', '.join(unknown)}",
        )
    tiers = set(competition.difficulty_tiers or [])
    if challenge.difficulty is not None and challenge.difficulty not in tiers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown difficulty tier for this competition",
        )


def _validate_scoring(challenge: Challenge) -> None:
    """Dynamic scoring needs a floor and a decay, and the floor can't exceed the
    initial value (§13.2). Static challenges ignore both fields."""
    if challenge.scoring_type != "dynamic":
        return
    if challenge.min_points is None or challenge.decay is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dynamic scoring needs a minimum value and a decay",
        )
    if challenge.decay < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Decay must be at least 1",
        )
    if challenge.min_points > challenge.points:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Minimum value can't exceed the initial value",
        )


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


def _is_released(challenge: Challenge) -> bool:
    """Whether a challenge's scheduled release time (if any) has arrived."""
    return (
        challenge.release_at is None
        or ensure_aware_utc(challenge.release_at) <= utcnow()
    )


async def load_visible_challenge(
    db: AsyncSession, competition_id: str, challenge_id: str, user: User
) -> Challenge:
    """Return a scoped challenge, hiding what a competitor shouldn't see yet — a
    draft, or a published challenge whose scheduled release hasn't arrived — as a
    404 (indistinguishable from missing). Editors see everything. Shared by
    challenge and attachment reads."""
    challenge = await _get_scoped_challenge(db, competition_id, challenge_id)
    hidden = challenge.state != "published" or not _is_released(challenge)
    if hidden and not await user_has_permission(
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
        # Competitors see only published challenges whose scheduled release (if
        # any) has arrived; staff see everything.
        query = query.where(
            Challenge.state == "published",
            or_(
                Challenge.release_at.is_(None),
                Challenge.release_at <= utcnow(),
            ),
        )
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
    # Multiple-choice guesses remaining (competition-wide cap), per subject.
    limit = competition.mc_guess_limit if competition is not None else None
    attempts = (
        await subject_attempt_counts(db, competition_id, subject)
        if subject is not None and limit is not None
        else {}
    )
    # The requesting user's own ratings (for the post-solve prompt), when enabled.
    ratings: dict[str, int] = {}
    if competition is not None and competition.challenge_ratings_enabled:
        ratings = {
            cid: r
            for cid, r in (
                await db.execute(
                    select(ChallengeRating.challenge_id, ChallengeRating.rating).where(
                        ChallengeRating.competition_id == competition_id,
                        ChallengeRating.user_id == current_user.id,
                    )
                )
            ).all()
        }
    for challenge in challenges:
        challenge.solve_count = counts.get(challenge.id, 0)
        challenge.value = challenge_value(challenge, challenge.solve_count)
        challenge.solved = challenge.id in solved
        # Locked = a prerequisite the subject hasn't solved. Staff see everything
        # unlocked; a subjectless viewer (manager not on a team) also isn't gated.
        challenge.locked = (
            not can_edit and subject is not None and _is_locked(challenge, solved)
        )
        challenge.my_rating = ratings.get(challenge.id)
        if challenge.flag_type == "multiple_choice" and limit is not None:
            challenge.attempts_remaining = (
                None
                if challenge.id in solved
                else max(0, limit - attempts.get(challenge.id, 0))
            )
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
    challenge.value = challenge_value(challenge, challenge.solve_count)
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
    # Locked = an unsolved prerequisite (per subject; staff/subjectless unlocked).
    if _prereq_ids(challenge) and subject is not None:
        can_edit = await user_has_permission(
            db, current_user.id, "challenge_edit", competition_id
        )
        if not can_edit:
            solved_ids = await solved_challenge_ids(db, competition_id, subject)
            challenge.locked = _is_locked(challenge, solved_ids)
    limit = competition.mc_guess_limit if competition is not None else None
    if (
        challenge.flag_type == "multiple_choice"
        and limit is not None
        and subject is not None
        and not challenge.solved
    ):
        used = await subject_attempt_count(db, challenge_id, subject)
        challenge.attempts_remaining = max(0, limit - used)
    if competition is not None and competition.challenge_ratings_enabled:
        challenge.my_rating = await db.scalar(
            select(ChallengeRating.rating).where(
                ChallengeRating.challenge_id == challenge_id,
                ChallengeRating.user_id == current_user.id,
            )
        )
    return challenge


@router.get("/{challenge_id}/solves", response_model=list[ChallengeSolver])
async def list_solves(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeSolver]:
    """Who solved this challenge, earliest first (the first is the first blood).
    Visible to anyone who can see the challenge — the same disclosure the
    scoreboard already makes."""
    # 404s a draft for non-editors + enforces competition scoping.
    await load_visible_challenge(db, competition_id, challenge_id, current_user)
    competition = await db.get(Competition, competition_id)
    team_mode = competition is not None and competition.participation_mode == "team"
    subj_col = Submission.team_id if team_mode else Submission.user_id
    scope = (
        Submission.team_id.isnot(None)
        if team_mode
        else Submission.team_id.is_(None)
    )
    rows = (
        await db.execute(
            select(subj_col, Submission.created_at)
            .where(
                Submission.challenge_id == challenge_id,
                Submission.is_correct.is_(True),
                Submission.is_duplicate.is_(False),
                scope,
            )
            .order_by(Submission.created_at)
        )
    ).all()
    if not rows:
        return []

    # Resolve subject names in one query (team name, or user display name).
    ids = [sid for sid, _ in rows]
    if team_mode:
        name_rows = (
            await db.execute(select(Team.id, Team.name).where(Team.id.in_(ids)))
        ).all()
    else:
        name_rows = (
            await db.execute(
                select(User.id, User.display_name).where(User.id.in_(ids))
            )
        ).all()
    names = dict(name_rows)

    return [
        ChallengeSolver(
            subject_id=sid,
            name=names.get(sid, "—"),
            solved_at=solved_at,
            is_first_blood=(i == 0),
        )
        for i, (sid, solved_at) in enumerate(rows)
    ]


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
        scoring_type=body.scoring_type,
        min_points=body.min_points,
        decay=body.decay,
        release_at=body.release_at,
        prerequisites=body.prerequisites or None,
        tags=body.tags or None,
        difficulty=body.difficulty,
        flag_type=body.flag_type,
        case_insensitive=body.case_insensitive,
    )
    _validate_scoring(challenge)
    await _validate_prerequisites(
        db, competition_id, None, _prereq_ids(challenge)
    )
    competition = await db.get(Competition, competition_id)
    if competition is not None:
        _validate_metadata(competition, challenge)
    if body.flag_type == "multiple_choice" and body.choices is not None:
        challenge.choices = body.choices
        _validate_multiple_choice(challenge, body.flag)
    if body.flag is not None:
        _apply_flag(challenge, body.flag)
    db.add(challenge)
    await db.commit()
    challenge.value = challenge_value(challenge, 0)  # brand-new: no solves yet

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
    _validate_scoring(challenge)
    if "prerequisites" in changes:
        challenge.prerequisites = challenge.prerequisites or None
        await _validate_prerequisites(
            db, competition_id, challenge.id, _prereq_ids(challenge)
        )
    if "tags" in changes or "difficulty" in changes:
        challenge.tags = challenge.tags or None
        competition = await db.get(Competition, competition_id)
        if competition is not None:
            _validate_metadata(competition, challenge)

    # Multiple-choice options can't be verified against the already-hashed answer,
    # so a change to the option set (or a switch into multiple_choice) requires
    # re-supplying the correct answer alongside the options.
    if challenge.flag_type == "multiple_choice":
        challenge.choices = challenge.choices or None
        if "choices" in changes and raw_flag is None and challenge.flag_hash is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Re-enter the correct answer when changing the options",
            )
        if challenge.choices:
            _validate_multiple_choice(challenge, raw_flag)
    else:
        # Leaving multiple_choice drops the now-meaningless option list.
        challenge.choices = None

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
    await _set_value(db, challenge)
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
    await _set_value(db, challenge)
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
    await _set_value(db, challenge)
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


@router.post("/{challenge_id}/reset-guesses", status_code=status.HTTP_204_NO_CONTENT)
async def reset_guesses(
    competition_id: str,
    challenge_id: str,
    body: ResetGuessesRequest,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Give a subject (or everyone) a fresh set of multiple-choice guesses,
    non-destructively (§13.2) — records a cutoff, keeps submission history."""
    challenge = await _get_scoped_challenge(db, competition_id, challenge_id)
    if challenge.flag_type != "multiple_choice":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Guess resets only apply to multiple-choice challenges",
        )
    if body.user_id and body.team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset a team or a user, not both",
        )
    if body.team_id is not None:
        team = await db.scalar(
            select(Team).where(
                Team.id == body.team_id, Team.competition_id == competition_id
            )
        )
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
            )
    if body.user_id is not None and await db.get(User, body.user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    db.add(
        MCGuessReset(
            competition_id=competition_id,
            challenge_id=challenge_id,
            user_id=body.user_id,
            team_id=body.team_id,
            reset_by=current_user.id,
        )
    )
    await db.commit()

    await event_bus.emit(
        "challenge.guesses_reset",
        {
            "competition_id": competition_id,
            "challenge_id": challenge_id,
            "user_id": body.user_id,
            "team_id": body.team_id,
            "actor_user_id": current_user.id,
        },
    )
