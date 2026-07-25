"""Flag submission + scoring (ROADMAP #11/#12, ARCHITECTURE.md §13.2).

The one adversarial endpoint in the product. Hardening, in order (§13.2):

1. **Gated by ``challenge_view``** and scoped by the path's ``competition_id``
   (§6.2, §7.6) — you can only submit against a challenge you can see, and a
   draft stays 404 to non-editors (via ``load_visible_challenge``).
2. **Per-subject rate limit** (tighter than general API limits) *before* any
   flag comparison, so a guessing script is throttled whether it's right or not.
3. **Server-side comparison only** — the stored hash/pattern never leaves the
   server; verification reuses ``utils/flags`` so authoring and grading can't
   drift (§13.2).
4. **Every attempt is logged** — a row per try, success or failure.
5. **Idempotent on repeat-correct** — the first correct submission by a subject
   is authoritative; later correct ones are logged as duplicates and award
   nothing, and ``challenge.solved`` fires exactly once per subject.

The scoring subject is the team (team-mode) or the user (individual-mode),
resolved in ``utils/scoring`` so this route never re-derives it.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission, user_has_permission
from config import settings
from db import get_db
from models.challenge import Challenge
from models.competition import Competition
from models.submission import Submission
from models.user import User
from ratelimit import get_rate_limiter
from ratelimit.base import RateLimiter
from routers.challenges import load_visible_challenge
from schemas.submission import SubmitFlagRequest, SubmitResult
from utils.event_bus import event_bus
from utils.flags import verify_regex_flag, verify_static_flag
from utils.scoring import (
    challenge_value,
    resolve_subject,
    solved_challenge_ids,
    subject_attempt_count,
    subject_has_solved,
)

router = APIRouter(
    prefix="/api/competitions/{competition_id}/challenges/{challenge_id}",
    tags=["submissions"],
)


def _flag_matches(challenge: Challenge, submitted: str) -> bool:
    """Grade ``submitted`` against the challenge's stored flag config (§13.2)."""
    if challenge.flag_type == "regex":
        if challenge.flag_regex is None:
            return False
        return verify_regex_flag(
            submitted, challenge.flag_regex, challenge.case_insensitive
        )
    if challenge.flag_hash is None or challenge.flag_salt is None:
        return False
    return verify_static_flag(
        submitted, challenge.flag_salt, challenge.case_insensitive, challenge.flag_hash
    )


@router.post("/submit", response_model=SubmitResult)
async def submit_flag(
    competition_id: str,
    challenge_id: str,
    body: SubmitFlagRequest,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> SubmitResult:
    challenge = await load_visible_challenge(
        db, competition_id, challenge_id, current_user
    )
    if not challenge.has_flag:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This challenge has no flag to submit against",
        )

    competition = await db.get(Competition, competition_id)

    # Paused competition (§13.2): gameplay is halted — competitors can't submit.
    # Staff (challenge_edit) bypass so they can still test while paused.
    if competition.paused and not await user_has_permission(
        db, current_user.id, "challenge_edit", competition_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The competition is paused — submissions are closed",
        )

    subject = await resolve_subject(db, competition, current_user)
    if subject is None:
        # Team-mode competitor who hasn't joined a team — nothing to credit.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Join a team before submitting flags",
        )

    # Unlock chains (§13.2): a locked challenge (unsolved prerequisite) can't be
    # submitted against until its prerequisites are met, for this subject.
    prereqs = list(challenge.prerequisites or [])
    if prereqs:
        solved_ids = await solved_challenge_ids(db, competition_id, subject)
        if any(pid not in solved_ids for pid in prereqs):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solve this challenge's prerequisites first",
            )

    # Rate limit the *subject* across the competition, before grading, so
    # rotating challenges doesn't sidestep the throttle (§13.2).
    allowed = await rate_limiter.hit(
        f"submit:{competition_id}:{subject.kind}:{subject.id}",
        limit=settings.submission_rate_limit,
        window_seconds=settings.submission_rate_window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many submissions — slow down and try again shortly",
        )

    # Multiple-choice guess cap (competition-wide, §13.2): a finite option set is
    # trivially brute-forced, so once a subject has used its allotted guesses on an
    # unsolved MC challenge, further guesses are refused. Checked before grading so
    # the block can't be probed for correctness.
    limit = competition.mc_guess_limit
    if (
        challenge.flag_type == "multiple_choice"
        and limit is not None
        and not await subject_has_solved(db, challenge_id, subject)
        and await subject_attempt_count(db, challenge_id, subject) >= limit
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No guesses remaining for this question",
        )

    # Grade off the event-loop thread: a regex flag runs a bounded but
    # potentially heavy match (ADR-0018), and `regex` releases the GIL, so a
    # single match never stalls the loop for other requests. (Static/MC grading
    # is trivially fast; the offload is uniform and harmless there.)
    correct = await asyncio.to_thread(_flag_matches, challenge, body.flag)
    already_solved = correct and await subject_has_solved(db, challenge_id, subject)
    award = correct and not already_solved

    is_first_blood = False
    points_awarded = 0
    if award:
        # First blood = no subject has an awarded solve on this challenge yet.
        prior_solves = await db.scalar(
            select(func.count(Submission.id)).where(
                Submission.challenge_id == challenge_id,
                Submission.is_correct.is_(True),
                Submission.is_duplicate.is_(False),
            )
        )
        is_first_blood = prior_solves == 0
        # This solve makes the count `prior_solves + 1`; a dynamic challenge is
        # then worth less, and *every* solver converges to that current value.
        points_awarded = challenge_value(challenge, prior_solves + 1)

    # Every attempt is logged — success, failure, or duplicate (§13.2).
    db.add(
        Submission(
            competition_id=competition_id,
            challenge_id=challenge_id,
            user_id=current_user.id,
            team_id=subject.team_id,
            value=body.flag,
            is_correct=correct,
            is_duplicate=correct and already_solved,
            points_awarded=points_awarded,
        )
    )
    if award and challenge.scoring_type == "dynamic":
        # Re-value the prior solvers to the new (lower) worth so the board stays
        # consistent — every solve of a dynamic challenge is worth the same now.
        await db.execute(
            update(Submission)
            .where(
                Submission.challenge_id == challenge_id,
                Submission.is_correct.is_(True),
                Submission.is_duplicate.is_(False),
            )
            .values(points_awarded=points_awarded)
        )
    await db.commit()

    # Every graded submission emits challenge.attempted (right or wrong) — the
    # event half of "every attempt is logged" above, and what keeps attempt
    # counters (dashboard stats, challenge health, analytics) live. Refusals
    # before grading (rate limit, MC cap, locked) emit nothing.
    await event_bus.emit(
        "challenge.attempted",
        {
            "competition_id": competition_id,
            "challenge_id": challenge_id,
            "user_id": current_user.id,
            "team_id": subject.team_id,
            "correct": correct,
        },
    )
    if award:
        await event_bus.emit(
            "challenge.solved",
            {
                "competition_id": competition_id,
                "challenge_id": challenge_id,
                "user_id": current_user.id,
                "team_id": subject.team_id,
                "points": points_awarded,
                "is_first_blood": is_first_blood,
            },
        )

    attempts_remaining: int | None = None
    if challenge.flag_type == "multiple_choice" and limit is not None and not correct:
        # This submission is now logged, so recount reflects it.
        used = await subject_attempt_count(db, challenge_id, subject)
        attempts_remaining = max(0, limit - used)

    return SubmitResult(
        correct=correct,
        already_solved=already_solved,
        points_awarded=points_awarded,
        is_first_blood=is_first_blood,
        attempts_remaining=attempts_remaining,
    )
