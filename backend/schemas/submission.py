"""Pydantic schemas for flag submission (§13.2).

The flag goes **in** as plaintext and is compared server-side; nothing about the
stored flag ever comes back. The result reports only what the competitor needs:
whether it was correct, whether they'd already solved it, the points awarded,
and whether they took first blood.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SubmitFlagRequest(BaseModel):
    flag: str = Field(min_length=1, max_length=500)


class SubmitResult(BaseModel):
    correct: bool
    # True when the flag was correct but the subject had already solved the
    # challenge — no points are awarded a second time (§13.2 idempotency).
    already_solved: bool = False
    points_awarded: int = 0
    # True only on the first correct solve of this challenge in the competition.
    is_first_blood: bool = False
    # Guesses left for the subject on a multiple-choice challenge under the
    # competition-wide cap (null = no cap, not multiple-choice, or already solved).
    attempts_remaining: int | None = None
    # The base worth before the multiple-choice wrong-guess penalty (#148), so the
    # solve result can show "reduced from N". Null unless a penalty actually
    # lowered this award (i.e. points_awarded < full_value).
    full_value: int | None = None
    # The subject's *current* worth going forward after this attempt, under the
    # wrong-guess penalty (#148) — returned on an incorrect guess so the client can
    # drop the displayed value live without waiting for a challenge refetch. Null
    # when no penalty has reduced it (penalty off, not multiple-choice, or first
    # guess still at full value).
    subject_value: int | None = None


class SubmissionCorrectness(str, Enum):
    """Three mutually-exclusive buckets over the ``is_correct``/``is_duplicate``
    columns (§13.2) for the staff submissions browser (ROADMAP #76). "duplicate"
    keeps its existing meaning here — a correct flag the subject had already
    solved — not "this exact payload string was tried before"."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    DUPLICATE = "duplicate"


class SubmissionOut(BaseModel):
    """One raw submission attempt, for the judge/admin dispute-resolution
    browser. The exact submitted payload and timestamp — never redacted, unlike
    the competitor-facing ``SubmitResult``, since this surface is staff-only."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    challenge_id: str
    user_id: str
    team_id: str | None
    value: str
    correctness: SubmissionCorrectness
    points_awarded: int
    created_at: datetime


class SubmissionPage(BaseModel):
    """One page of submission-browser results plus the total match count for
    pagination, mirroring ``AuditLogPage``."""

    items: list[SubmissionOut]
    total: int
    limit: int
    offset: int
