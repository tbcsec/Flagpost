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
from sqlalchemy import func, select
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
from utils.competition_status import require_playable
from utils.event_bus import event_bus
from utils.flags import verify_regex_flag, verify_static_flag
from utils.grading import emit_grade, lock_subject, record_grade
from utils.instance_grading import deployment_flag_mode, grade_unique
from utils.scoreboard import visible_solve_cutoff
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
    if challenge.flag_type == "programming":
        # Marked by the code judge (#447/#448), never by a submitted string.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Programming challenges are solved by submitting code, not a flag",
        )
    # Unique-per-instance mode (ADR-0036 §3) lives on the challenge's deployment,
    # not the Challenge row — so the flag is graded against the subject's live
    # instance, and the challenge itself may carry no static flag. One indexed
    # lookup, then it also drives the grading branch below.
    unique_mode = (
        await deployment_flag_mode(db, competition_id, challenge_id)
        == "unique_per_instance"
    )
    if not challenge.has_flag and not unique_mode:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This challenge has no flag to submit against",
        )

    competition = await db.get(Competition, competition_id)

    # Competition status gate (#221): submissions are closed unless the competition
    # is running (staff bypass) — checked before the pause gate so a not_started /
    # ended competition gives the clearer "hasn't started / has ended" message.
    await require_playable(db, competition, current_user.id)

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
        await lock_subject(db, subject)
        if not await subject_has_solved(
            db, challenge_id, subject
        ) and await subject_attempt_count(db, challenge_id, subject) >= limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No guesses remaining for this question",
            )

    # Unique-per-instance grading (ADR-0036 §3): compare against the subject's
    # own live instance flag(s), not the challenge's static config. A wrong
    # submission that matches ANOTHER subject's live flag is provable sharing —
    # captured here, emitted after commit. Otherwise grade off the event-loop
    # thread: a regex flag runs a bounded but potentially heavy match (ADR-0018),
    # and `regex` releases the GIL, so a single match never stalls the loop.
    # (Static/MC grading is trivially fast; the offload is uniform and harmless.)
    shared_flag_match = None
    if unique_mode:
        grade = await grade_unique(
            db, competition_id, challenge_id, subject, body.flag,
            user_id=current_user.id,
        )
        correct = grade.correct
        shared_flag_match = grade.shared_with
    else:
        correct = await asyncio.to_thread(_flag_matches, challenge, body.flag)
    # Record it — the shared award path (utils/grading), which the code judge
    # uses too: duplicate check, first blood, value, race-safe insert, dynamic
    # re-value. Commit, then emit.
    grade = await record_grade(
        db,
        competition=competition,
        challenge=challenge,
        subject=subject,
        user_id=current_user.id,
        value=body.flag,
        correct=correct,
    )
    await db.commit()
    await emit_grade(
        grade,
        competition_id=competition_id,
        challenge_id=challenge_id,
        user_id=current_user.id,
        team_id=subject.team_id,
    )
    already_solved = grade.already_solved
    points_awarded = grade.points_awarded
    is_first_blood = grade.is_first_blood
    base_value = grade.base_value
    mc_penalty = grade.mc_penalty
    if shared_flag_match is not None:
        # A wrong submission carried another subject's live per-instance flag —
        # provable flag sharing (ADR-0036 §3). Signal only, for staff and
        # automation; no automatic penalty, policy stays human. ids only.
        await event_bus.emit(
            "challenge.flag_shared_detected",
            {
                "competition_id": competition_id,
                "challenge_id": challenge_id,
                "user_id": current_user.id,
                "team_id": subject.team_id,
                "matched_user_id": shared_flag_match.user_id,
                "matched_team_id": shared_flag_match.team_id,
                "instance_id": shared_flag_match.instance_id,
            },
        )

    # Under a freeze (GHSA-r7j2) a competitor's own result mustn't say what the
    # frozen board hides: whether anyone has solved this since the cutoff (first
    # blood), or — for a dynamic challenge, whose worth is a function of its solve
    # count — the live value. "Correct" stands; those fields go null until
    # unfreeze. Staff (scoreboard_freeze) get the live figures, as on the board.
    cutoff = await visible_solve_cutoff(db, competition, current_user)
    if cutoff is not None and grade.award:
        is_first_blood = None
        if challenge.scoring_type == "dynamic":
            points_awarded = None
            base_value = None

    attempts_remaining: int | None = None
    subject_value: int | None = None
    penalty_pct = competition.mc_penalty_pct
    if (
        challenge.flag_type == "multiple_choice"
        and not correct
        and (limit is not None or penalty_pct)
    ):
        # This submission is now logged, so the recount reflects it.
        used = await subject_attempt_count(db, challenge_id, subject)
        if limit is not None:
            attempts_remaining = max(0, limit - used)
        if penalty_pct:
            # The subject's worth going forward, so the client can drop the shown
            # value live rather than waiting for a challenge refetch (#148). Base
            # is the current value (static points, or the dynamic worth at the
            # solve count — as of the freeze cutoff for a frozen-out competitor,
            # like the card it replaces); null when nothing's been docked yet.
            solved = [
                Submission.challenge_id == challenge_id,
                Submission.is_correct.is_(True),
                Submission.is_duplicate.is_(False),
            ]
            if cutoff is not None:
                solved.append(Submission.created_at <= cutoff)
            solve_count = (
                (await db.scalar(select(func.count(Submission.id)).where(*solved)))
                or 0
                if challenge.scoring_type == "dynamic"
                else 0
            )
            base_now = challenge_value(challenge, solve_count)
            reduced = penalised_value(base_now, penalty_pct, used)
            subject_value = reduced if reduced < base_now else None

    return SubmitResult(
        correct=correct,
        already_solved=already_solved,
        points_awarded=points_awarded,
        is_first_blood=is_first_blood,
        attempts_remaining=attempts_remaining,
        # The pre-penalty worth, so the UI can show "reduced from N" — only when a
        # multiple-choice penalty actually docked this solve (#148).
        full_value=base_value if mc_penalty > 0 else None,
        subject_value=subject_value,
    )
