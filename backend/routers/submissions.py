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
from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.exc import IntegrityError

from auth.deps import require_permission, user_has_permission
from config import settings
from db import get_db
from models.challenge import Challenge
from models.competition import Competition
from models.submission import Submission
from models.team import Team
from models.user import User
from ratelimit import get_rate_limiter
from ratelimit.base import RateLimiter
from routers.challenges import load_visible_challenge
from schemas.submission import SubmitFlagRequest, SubmitResult
from utils.event_bus import event_bus
from utils.flags import verify_regex_flag, verify_static_flag
from utils.scoring import (
    challenge_value,
    penalised_value,
    resolve_subject,
    solved_challenge_ids,
    subject_attempt_count,
    subject_has_solved,
)

router = APIRouter(
    prefix="/api/competitions/{competition_id}/challenges/{challenge_id}",
    tags=["submissions"],
)


async def _lock_subject(db: AsyncSession, subject) -> None:
    """Take a row lock on the scoring subject for the rest of this transaction.

    Serialises concurrent submissions from the same team (or user) so a
    check-then-insert sequence can't interleave with itself. The lock is on a row
    that already exists and is never updated here, so it costs a row-level lock
    and nothing else.

    A no-op on SQLite, which has no ``FOR UPDATE`` — but SQLite serialises
    writers globally, so the interleaving this prevents cannot occur there
    either. Postgres is where it matters, and Postgres is production.
    """
    model, key = (Team, subject.team_id) if subject.kind == "team" else (User, subject.id)
    if key is None:
        return
    await db.execute(select(model.id).where(model.id == key).with_for_update())


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
    if challenge.flag_type == "multiple_choice" and limit is not None:
        # Serialise this subject's guesses before counting them. The count is a
        # plain SELECT over committed rows, so without a lock a burst of
        # concurrent guesses — one per option, at most ten, comfortably inside
        # the submission rate limit — all read the same pre-burst count and all
        # get graded. That defeats the cap on precisely the challenge type it
        # exists for. Confined to multiple-choice, so static and regex flags
        # take no extra lock on the hot path.
        await _lock_subject(db, subject)
        if not await subject_has_solved(
            db, challenge_id, subject
        ) and await subject_attempt_count(db, challenge_id, subject) >= limit:
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
    base_value = 0
    mc_penalty = 0
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
        base_value = challenge_value(challenge, prior_solves + 1)
        points_awarded = base_value
        # Multiple-choice wrong-guess penalty (#148): dock the award by
        # mc_penalty_pct per prior incorrect guess. At this point every submission
        # this subject has made against the challenge since its last reset is a
        # wrong guess — the current correct one isn't inserted yet, and a prior
        # correct one would have made this a duplicate (award would be False). So
        # the reset-aware attempt count is exactly the wrong-guess count.
        if challenge.flag_type == "multiple_choice" and competition.mc_penalty_pct:
            wrong_guesses = await subject_attempt_count(db, challenge_id, subject)
            points_awarded = penalised_value(
                base_value, competition.mc_penalty_pct, wrong_guesses
            )
            mc_penalty = base_value - points_awarded

    def _row(*, duplicate: bool, points: int, penalty: int = 0) -> Submission:
        # Every attempt is logged — success, failure, or duplicate (§13.2).
        return Submission(
            competition_id=competition_id,
            challenge_id=challenge_id,
            user_id=current_user.id,
            team_id=subject.team_id,
            value=body.flag,
            is_correct=correct,
            is_duplicate=duplicate,
            points_awarded=points,
            mc_penalty=penalty,
        )

    if award:
        # Insert inside a SAVEPOINT so losing the race is recoverable. The
        # partial unique index on (challenge, subject) is what actually enforces
        # "first correct submission wins" — the read-then-write above can't,
        # since both requests query before either commits. Catching this at the
        # outer commit instead would leave the session unusable and turn a lost
        # race into a 500.
        try:
            async with db.begin_nested():
                db.add(_row(duplicate=False, points=points_awarded, penalty=mc_penalty))
                await db.flush()
        except IntegrityError:
            # Another submission for this subject got there first. Record what
            # actually happened — a duplicate, worth nothing — rather than
            # paying the flag out twice.
            award = False
            already_solved = True
            is_first_blood = False
            points_awarded = 0
            db.add(_row(duplicate=True, points=0))
    else:
        db.add(_row(duplicate=correct and already_solved, points=points_awarded))

    if award and challenge.scoring_type == "dynamic":
        # Re-value the prior solvers to the new (lower) base worth so the board
        # stays consistent — but preserve each solver's own multiple-choice
        # penalty (#148) instead of collapsing everyone to a single value, which
        # would overwrite a penalised solver's award with this solver's. For every
        # non-penalised row mc_penalty is 0, so this stays exactly "converge to the
        # new value", unchanged from before. Floored at 0 with a portable CASE
        # (SQLite has no GREATEST); the current row nets back to points_awarded.
        net = base_value - Submission.mc_penalty
        await db.execute(
            update(Submission)
            .where(
                Submission.challenge_id == challenge_id,
                Submission.is_correct.is_(True),
                Submission.is_duplicate.is_(False),
            )
            .values(points_awarded=case((net < 0, 0), else_=net))
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
        # The pre-penalty worth, so the UI can show "reduced from N" — only when a
        # multiple-choice penalty actually docked this solve (#148).
        full_value=base_value if mc_penalty > 0 else None,
    )
