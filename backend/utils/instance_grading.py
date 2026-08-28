"""Unique-per-instance flag grading (#266 Phase 2a, ADR-0036 §3).

Kept out of ``routers/submissions.py`` so the grading path stays lean and the
unique-mode resolution — the submitter's active-instance lookup, the salted-hash
compare, and the cross-subject flag-sharing scan — is independently testable.

The tables queried here always exist (created by the instancing migration), so
this is safe to call from the core submission path: a challenge is unique-mode
only when it has a ``ChallengeDeployment`` with ``flag_mode ==
"unique_per_instance"``, and every other challenge falls through untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.challenge_instancing import (
    INSTANCE_ACTIVE_STATUSES,
    ChallengeDeployment,
    ChallengeInstance,
)
from utils.flags import verify_static_flag

# Instance flags are machine-rendered random tokens (utils.instance_service.
# render_flag_template), so they are compared exactly — never case-folded. This
# MUST match the case_insensitive value used to hash them at provision time.
_CASE_INSENSITIVE = False


@dataclass(frozen=True)
class SharedFlagMatch:
    """A wrong submission that matched another subject's live instance flag —
    the ids needed for the ``challenge.flag_shared_detected`` payload. Captured
    as primitives while the session is live, so it survives the post-commit emit
    without a lazy load."""

    instance_id: str
    user_id: str
    team_id: str | None


@dataclass(frozen=True)
class UniqueGrade:
    """Verdict of grading a submission against a challenge's per-instance flags.
    ``shared_with`` is set only on a WRONG submission that matched ANOTHER
    subject's active instance — provable flag sharing (ADR-0036 §3)."""

    correct: bool
    shared_with: SharedFlagMatch | None = None


async def deployment_flag_mode(
    db: AsyncSession, competition_id: str, challenge_id: str
) -> str | None:
    """The challenge's deployment ``flag_mode``, or ``None`` when the challenge
    has no deployment. One indexed lookup (``challenge_deployments.challenge_id``
    is unique). Competition-scoped per §6.2."""
    return await db.scalar(
        select(ChallengeDeployment.flag_mode).where(
            ChallengeDeployment.competition_id == competition_id,
            ChallengeDeployment.challenge_id == challenge_id,
        )
    )


async def _gradeable_instances(
    db: AsyncSession, competition_id: str, challenge_id: str
) -> list[ChallengeInstance]:
    """Active instances of the challenge that already hold a flag hash. A
    ``requested``/``provisioning`` instance is active but has no hash yet (it is
    written at the ``running`` transition), so it is not gradeable. Competition-
    scoped (§6.2), even though ``challenge_id`` already implies it."""
    result = await db.scalars(
        select(ChallengeInstance).where(
            ChallengeInstance.competition_id == competition_id,
            ChallengeInstance.challenge_id == challenge_id,
            ChallengeInstance.status.in_(INSTANCE_ACTIVE_STATUSES),
            ChallengeInstance.flag_hash.is_not(None),
        )
    )
    return list(result)


def _subject_of(instance: ChallengeInstance) -> str:
    """The credited subject key — team in team mode, user otherwise (mirrors the
    awarded-solve index and ``instance_service.subject_key``)."""
    return instance.team_id or instance.user_id


async def grade_unique(
    db: AsyncSession,
    competition_id: str,
    challenge_id: str,
    subject,
    submitted: str,
    *,
    user_id: str,
) -> UniqueGrade:
    """Grade ``submitted`` against per-instance flags (ADR-0036 §3).

    Correct iff it matches one of the SUBMITTING subject's own active instances
    (``per_subject_cap`` may be > 1, so any match counts). On a miss, scan the
    OTHER subjects' active instances — a match there is provable flag sharing and
    is reported via ``shared_with`` (the verdict stays wrong; no auto-penalty).

    ``user_id`` is the submitting human. The sharing scan excludes any instance
    that submitter launched (by ``user_id``) as well as their current subject —
    so a competitor who switched teams while holding a live instance credited to
    the old team can't be flagged for "sharing" their own former flag.

    Each instance carries its own salt, so the compare is per-row and cannot be a
    single indexed lookup; the candidate set is bounded by the concurrency caps.
    """
    instances = await _gradeable_instances(db, competition_id, challenge_id)
    # The submitter's own live flag(s) grade a correct solve.
    for inst in instances:
        if _subject_of(inst) == subject.id and verify_static_flag(
            submitted, inst.flag_salt, _CASE_INSENSITIVE, inst.flag_hash
        ):
            return UniqueGrade(correct=True)
    # Wrong for this subject — did they submit *someone else's* live flag? Skip
    # any instance the submitter owns (current subject key or the same human) so
    # a team switch can't turn into a self-accusation.
    for inst in instances:
        if _subject_of(inst) == subject.id or inst.user_id == user_id:
            continue
        if verify_static_flag(
            submitted, inst.flag_salt, _CASE_INSENSITIVE, inst.flag_hash
        ):
            return UniqueGrade(
                correct=False,
                shared_with=SharedFlagMatch(
                    instance_id=inst.id,
                    user_id=inst.user_id,
                    team_id=inst.team_id,
                ),
            )
    return UniqueGrade(correct=False)
