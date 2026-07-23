"""Pydantic schemas for flag submission (§13.2).

The flag goes **in** as plaintext and is compared server-side; nothing about the
stored flag ever comes back. The result reports only what the competitor needs:
whether it was correct, whether they'd already solved it, the points awarded,
and whether they took first blood.
"""

from pydantic import BaseModel, Field


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
