"""Recording a graded submission — the one award path (ADR-0042 §4).

A flag submission and an accepted code judging both end the same way: an
ordinary ``Submission`` row. Every read path — scoreboard, decay, first blood,
freeze, brackets, skills, analytics, reports — keys off that row
(``is_correct AND NOT is_duplicate`` plus ``points_awarded``), so the judge
doesn't fork any of them; it calls this.

``record_grade`` does everything up to the commit: the duplicate check, first
blood, the value (dynamic decay, the multiple-choice penalty), the insert —
inside a savepoint, so losing a race to the partial unique index becomes a
duplicate rather than a double award — and the dynamic re-value sweep. The
caller commits, then ``emit_grade`` fires the events (commit before emitting:
the audit consumer has its own session).

``created_at`` lets the judge **backdate** the row to when the code was
submitted, not when the verdict landed: ``created_at`` is the solve time on
every read path, so otherwise queue depth would distort first-blood order and
freeze cutoffs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.challenge import Challenge
from models.competition import Competition
from models.submission import Submission
from models.team import Team
from models.user import User
from utils.event_bus import event_bus
from utils.scoring import (
    challenge_value,
    penalised_value,
    subject_attempt_count,
    subject_has_solved,
)


async def lock_subject(db: AsyncSession, subject) -> None:
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


@dataclass
class GradeOutcome:
    correct: bool
    award: bool
    already_solved: bool
    is_first_blood: bool
    points_awarded: int
    base_value: int
    mc_penalty: int
    submission: Submission


async def record_grade(
    db: AsyncSession,
    *,
    competition: Competition,
    challenge: Challenge,
    subject,
    user_id: str,
    value: str,
    correct: bool,
    created_at: datetime | None = None,
) -> GradeOutcome:
    challenge_id = challenge.id
    already_solved = correct and await subject_has_solved(db, challenge_id, subject)
    award = correct and not already_solved

    is_first_blood = False
    points_awarded = 0
    base_value = 0
    mc_penalty = 0
    if award:
        awarded = (
            Submission.challenge_id == challenge_id,
            Submission.is_correct.is_(True),
            Submission.is_duplicate.is_(False),
        )
        prior_solves = await db.scalar(select(func.count(Submission.id)).where(*awarded))
        # First blood = no subject has an awarded solve on this challenge yet —
        # or, for a backdated solve, none *earlier*: every read path ranks
        # solves by created_at, so this must agree with them. (With concurrent
        # judgings, a later-submitted judging can finish first and be announced
        # as first blood before an earlier one lands; the earlier one is then
        # announced too, and is the one the read paths show.)
        if created_at is None:
            is_first_blood = prior_solves == 0
        else:
            is_first_blood = not await db.scalar(
                select(func.count(Submission.id)).where(
                    *awarded, Submission.created_at < created_at
                )
            )
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
        row = Submission(
            competition_id=competition.id,
            challenge_id=challenge_id,
            user_id=user_id,
            team_id=subject.team_id,
            value=value,
            is_correct=correct,
            is_duplicate=duplicate,
            points_awarded=points,
            mc_penalty=penalty,
        )
        if created_at is not None:
            row.created_at = created_at
        return row

    if award:
        # Insert inside a SAVEPOINT so losing the race is recoverable. The
        # partial unique index on (challenge, subject) is what actually enforces
        # "first correct submission wins" — the read-then-write above can't,
        # since both requests query before either commits. Catching this at the
        # outer commit instead would leave the session unusable and turn a lost
        # race into a 500.
        try:
            async with db.begin_nested():
                row = _row(duplicate=False, points=points_awarded, penalty=mc_penalty)
                db.add(row)
                await db.flush()
        except IntegrityError:
            # Another submission for this subject got there first. Record what
            # actually happened — a duplicate, worth nothing — rather than
            # paying out twice.
            award = False
            already_solved = True
            is_first_blood = False
            points_awarded = 0
            row = _row(duplicate=True, points=0)
            db.add(row)
    else:
        row = _row(duplicate=correct and already_solved, points=points_awarded)
        db.add(row)

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

    return GradeOutcome(
        correct=correct,
        award=award,
        already_solved=already_solved,
        is_first_blood=is_first_blood,
        points_awarded=points_awarded,
        base_value=base_value,
        mc_penalty=mc_penalty,
        submission=row,
    )


async def emit_grade(
    outcome: GradeOutcome,
    *,
    competition_id: str,
    challenge_id: str,
    user_id: str,
    team_id: str | None,
) -> None:
    """The events for a committed grade."""
    # Every graded submission emits challenge.attempted (right or wrong) — the
    # event half of "every attempt is logged", and what keeps attempt counters
    # (dashboard stats, challenge health, analytics) live.
    await event_bus.emit(
        "challenge.attempted",
        {
            "competition_id": competition_id,
            "challenge_id": challenge_id,
            "user_id": user_id,
            "team_id": team_id,
            "correct": outcome.correct,
        },
    )
    if outcome.award:
        await event_bus.emit(
            "challenge.solved",
            {
                "competition_id": competition_id,
                "challenge_id": challenge_id,
                "user_id": user_id,
                "team_id": team_id,
                "points": outcome.points_awarded,
                "is_first_blood": outcome.is_first_blood,
            },
        )
