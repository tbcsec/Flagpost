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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.competition import Competition
from models.hint import HintReveal
from models.submission import Submission
from models.team import TeamMembership
from models.user import User


@dataclass(frozen=True)
class Subject:
    """Who a submission is credited to."""

    kind: str  # "team" | "user"
    id: str  # team_id (team mode) or user_id (individual mode)
    team_id: str | None  # the credited team, or None in individual mode


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


async def solve_counts(
    db: AsyncSession, competition_id: str
) -> dict[str, int]:
    """Map challenge_id -> number of distinct solving subjects, for a whole
    competition in one query (drives the browse list's ``solve_count``)."""
    rows = (
        await db.execute(
            select(Submission.challenge_id, func.count(Submission.id))
            .where(
                Submission.competition_id == competition_id,
                Submission.is_correct.is_(True),
                Submission.is_duplicate.is_(False),
            )
            .group_by(Submission.challenge_id)
        )
    ).all()
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
