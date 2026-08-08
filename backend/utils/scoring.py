"""Scoring subject resolution + solve-state helpers (§13.1, §13.2, ROADMAP #12).

A *subject* is who a solve is credited to: the **team** in a team-mode
competition, the **user** in individual-mode (§6, §11.3 — participation mode is
per-competition). Submission, scoring and the scoreboard all rank the same
subject, so the mapping lives here once rather than being re-derived per route.

Solve state is read off the ``submissions`` table: a subject has solved a
challenge iff it has any correct submission for it, and a challenge's solve
count is its number of first-correct (awarded, non-duplicate) submissions —
i.e. one per distinct solving subject.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.competition import Competition
from models.hint import HintReveal
from models.mc_guess_reset import MCGuessReset
from models.submission import Submission
from models.team import TeamMembership
from models.user import User


@dataclass(frozen=True)
class Subject:
    """Who a submission is credited to."""

    kind: str  # "team" | "user"
    id: str  # team_id (team mode) or user_id (individual mode)
    team_id: str | None  # the credited team, or None in individual mode


def dynamic_value(initial: int, minimum: int, decay: int, solve_count: int) -> int:
    """A dynamic challenge's current worth given how many subjects have solved it.

    The CTFd model: value falls quadratically from ``initial`` toward
    ``minimum`` over ``decay`` solves, then stays at ``minimum``. Every solver of
    the challenge is worth this same current value (the scoreboard converges them
    on each new solve), so the number shown on the card is exactly what each
    solve is worth right now.
    """
    if decay <= 0:
        return minimum if minimum > initial else initial
    value = ((minimum - initial) / (decay**2)) * (solve_count**2) + initial
    return max(int(round(value)), minimum)


def challenge_value(challenge, solve_count: int) -> int:
    """The current point worth of ``challenge`` given its solve count. Static
    challenges are always their fixed ``points``; dynamic ones decay (§13.2)."""
    if challenge.scoring_type == "dynamic":
        return dynamic_value(
            challenge.points,
            challenge.min_points or 0,
            challenge.decay or 0,
            solve_count,
        )
    return challenge.points


def penalised_value(base_value: int, penalty_pct: int | None, wrong_guesses: int) -> int:
    """A subject's award for a multiple-choice challenge after ``wrong_guesses``
    incorrect guesses, given the competition's per-guess penalty percentage (#148).

    Each wrong guess subtracts ``penalty_pct`` percent of the *base* value
    (``challenge_value`` — fixed points, or the current dynamic worth), applied
    linearly and floored at 0 (owner decision). ``penalty_pct`` null/0 or no wrong
    guesses returns ``base_value`` unchanged. This is the single source of truth
    for the penalty: the submit path bakes it into ``points_awarded`` and the read
    paths use it to show a competitor their reduced worth before they solve, so
    the two can't drift.
    """
    if not penalty_pct or wrong_guesses <= 0:
        return base_value
    penalty = round(base_value * (penalty_pct / 100) * wrong_guesses)
    return max(0, base_value - penalty)


async def resolve_subject(
    db: AsyncSession, competition: Competition, user: User
) -> Subject | None:
    """Resolve the scoring subject for ``user`` in ``competition``.

    Returns ``None`` when there is no valid subject — a team-mode competitor who
    hasn't joined a team yet (a manager viewing the board falls here too). The
    submit endpoint treats ``None`` as "join a team first"; read endpoints treat
    it as "no personal solve state".
    """
    if competition.participation_mode == "team":
        membership = await db.scalar(
            select(TeamMembership).where(
                TeamMembership.competition_id == competition.id,
                TeamMembership.user_id == user.id,
            )
        )
        if membership is None:
            return None
        return Subject(kind="team", id=membership.team_id, team_id=membership.team_id)
    return Subject(kind="user", id=user.id, team_id=None)


def _subject_solve_filter(subject: Subject):
    """WHERE clause matching a subject's own correct submissions."""
    if subject.kind == "team":
        return Submission.team_id == subject.id
    # Individual mode: the user's own solves, and only those (never a team row).
    return (Submission.user_id == subject.id) & (Submission.team_id.is_(None))


async def subject_has_solved(
    db: AsyncSession, challenge_id: str, subject: Subject
) -> bool:
    existing = await db.scalar(
        select(Submission.id).where(
            Submission.challenge_id == challenge_id,
            Submission.is_correct.is_(True),
            _subject_solve_filter(subject),
        )
    )
    return existing is not None


def _subject_reset_filter(subject: Subject):
    """WHERE clause matching resets targeted at a subject (mirrors solves)."""
    if subject.kind == "team":
        return MCGuessReset.team_id == subject.id
    return (MCGuessReset.user_id == subject.id) & (MCGuessReset.team_id.is_(None))


async def _reset_cutoff(
    db: AsyncSession, challenge_id: str, subject: Subject
):
    """The latest guess-reset that applies to ``subject`` on a challenge — a
    challenge-wide reset (both ids null) or one targeted at the subject. Guesses
    made at or before this instant don't count (Phase 9)."""
    return await db.scalar(
        select(func.max(MCGuessReset.created_at)).where(
            MCGuessReset.challenge_id == challenge_id,
            or_(
                and_(MCGuessReset.user_id.is_(None), MCGuessReset.team_id.is_(None)),
                _subject_reset_filter(subject),
            ),
        )
    )


async def subject_attempt_count(
    db: AsyncSession, challenge_id: str, subject: Subject
) -> int:
    """How many times ``subject`` has submitted against ``challenge_id`` (any
    outcome) since its last guess-reset. Drives the multiple-choice guess cap —
    every guess counts, so a team can't burn attempts across its members to
    sidestep the limit."""
    stmt = select(func.count(Submission.id)).where(
        Submission.challenge_id == challenge_id,
        _subject_solve_filter(subject),
    )
    cutoff = await _reset_cutoff(db, challenge_id, subject)
    if cutoff is not None:
        stmt = stmt.where(Submission.created_at > cutoff)
    return (await db.scalar(stmt)) or 0


async def subject_attempt_counts(
    db: AsyncSession, competition_id: str, subject: Subject
) -> dict[str, int]:
    """challenge_id -> ``subject``'s attempt count across the competition (the
    browse list's multiple-choice guesses-remaining). One grouped query, then a
    per-challenge recount only for the (rare) challenges that have a guess-reset."""
    rows = (
        await db.execute(
            select(Submission.challenge_id, func.count(Submission.id))
            .where(
                Submission.competition_id == competition_id,
                _subject_solve_filter(subject),
            )
            .group_by(Submission.challenge_id)
        )
    ).all()
    counts = {challenge_id: count for challenge_id, count in rows}

    # Apply reset cutoffs: for each reset challenge, recount from the cutoff.
    cutoff_rows = (
        await db.execute(
            select(MCGuessReset.challenge_id, func.max(MCGuessReset.created_at))
            .where(
                MCGuessReset.competition_id == competition_id,
                or_(
                    and_(
                        MCGuessReset.user_id.is_(None),
                        MCGuessReset.team_id.is_(None),
                    ),
                    _subject_reset_filter(subject),
                ),
            )
            .group_by(MCGuessReset.challenge_id)
        )
    ).all()
    for challenge_id, cutoff in cutoff_rows:
        if cutoff is None:
            continue
        counts[challenge_id] = (
            await db.scalar(
                select(func.count(Submission.id)).where(
                    Submission.challenge_id == challenge_id,
                    _subject_solve_filter(subject),
                    Submission.created_at > cutoff,
                )
            )
        ) or 0
    return counts


async def solve_counts(
    db: AsyncSession, competition_id: str, as_of=None
) -> dict[str, int]:
    """Map challenge_id -> number of distinct solving subjects, for a whole
    competition in one query (drives the browse list's ``solve_count``).

    ``as_of`` clamps the count to solves at or before that instant. Callers pass
    the freeze cutoff (``scoreboard.visible_solve_cutoff``): a live per-challenge
    solve count is enough to watch the endgame unfold through a frozen board.
    """
    stmt = select(Submission.challenge_id, func.count(Submission.id)).where(
        Submission.competition_id == competition_id,
        Submission.is_correct.is_(True),
        Submission.is_duplicate.is_(False),
    )
    if as_of is not None:
        stmt = stmt.where(Submission.created_at <= as_of)
    rows = (await db.execute(stmt.group_by(Submission.challenge_id))).all()
    return {challenge_id: count for challenge_id, count in rows}


async def solved_challenge_ids(
    db: AsyncSession, competition_id: str, subject: Subject
) -> set[str]:
    """The set of challenge ids ``subject`` has solved in the competition."""
    rows = (
        await db.execute(
            select(Submission.challenge_id)
            .where(
                Submission.competition_id == competition_id,
                Submission.is_correct.is_(True),
                _subject_solve_filter(subject),
            )
            .distinct()
        )
    ).all()
    return {challenge_id for (challenge_id,) in rows}


# --- Hint reveals (§13.2 subject semantics reused for Phase 9) ---------------


def _subject_reveal_filter(subject: Subject):
    """WHERE clause matching a subject's own hint reveals (mirrors solves)."""
    if subject.kind == "team":
        return HintReveal.team_id == subject.id
    return (HintReveal.user_id == subject.id) & (HintReveal.team_id.is_(None))


async def subject_has_revealed(
    db: AsyncSession, hint_id: str, subject: Subject
) -> bool:
    existing = await db.scalar(
        select(HintReveal.id).where(
            HintReveal.hint_id == hint_id,
            _subject_reveal_filter(subject),
        )
    )
    return existing is not None


async def revealed_hint_ids(
    db: AsyncSession, challenge_id: str, subject: Subject
) -> set[str]:
    """The set of hint ids ``subject`` has revealed on a challenge."""
    rows = (
        await db.execute(
            select(HintReveal.hint_id)
            .where(
                HintReveal.challenge_id == challenge_id,
                _subject_reveal_filter(subject),
            )
            .distinct()
        )
    ).all()
    return {hint_id for (hint_id,) in rows}
