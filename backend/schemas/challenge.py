"""Pydantic schemas for challenges.

The flag comes **in** on create/update as plaintext (over TLS, staff-only
endpoints) and never comes back out: output schemas expose only ``has_flag``
(§13.2). There is deliberately no schema field that could carry the hash,
salt, or regex outward.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FlagType = Literal["static", "regex", "multiple_choice"]
ChallengeState = Literal["draft", "published"]

# A multiple-choice option list: 2–10 options, each a short string.
Choices = list[str]


class ChallengeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: dict[str, Any] = Field(default_factory=dict)
    category_id: str | None = None
    points: int = Field(default=100, ge=0, le=100_000)
    flag_type: FlagType = "static"
    case_insensitive: bool = False
    # Plaintext flag (static), pattern (regex), or the **correct option**
    # (multiple_choice); optional so drafts can be sketched before the flag
    # exists. Publishing requires one.
    flag: str | None = Field(default=None, min_length=1, max_length=500)
    # The options shown for a multiple_choice challenge (the correct one is
    # `flag`, and must appear here). Ignored for other flag types.
    choices: Choices | None = Field(default=None, min_length=2, max_length=10)


class ChallengeUpdate(BaseModel):
    """PATCH body — only provided fields are applied. Sending ``flag`` (with
    ``flag_type``/``case_insensitive``/``choices`` as needed) replaces the stored flag."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: dict[str, Any] | None = None
    category_id: str | None = None
    points: int | None = Field(default=None, ge=0, le=100_000)
    flag_type: FlagType | None = None
    case_insensitive: bool | None = None
    flag: str | None = Field(default=None, min_length=1, max_length=500)
    choices: Choices | None = Field(default=None, min_length=2, max_length=10)


class ChallengeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    competition_id: str
    title: str
    description: dict[str, Any]
    category_id: str | None
    points: int
    state: ChallengeState
    flag_type: FlagType
    case_insensitive: bool
    has_flag: bool  # the only flag-related fact that ever leaves the server
    # The multiple-choice options a competitor picks from (the correct one is NOT
    # revealed). Null for static/regex challenges.
    choices: Choices | None = None
    # Guesses left for the requesting subject on a multiple_choice challenge under
    # the competition-wide cap. Null = no limit (or not multiple-choice). Computed
    # on the detail read; left None on create/update/publish responses.
    attempts_remaining: int | None = None
    # Solve state (Phase 6). ``solved`` is relative to the requesting subject —
    # the team (team-mode) or user (individual-mode); false for a viewer with no
    # subject (e.g. a manager not on a team). ``solve_count`` is the number of
    # distinct subjects that have solved it. Defaulted so the create/update/
    # publish responses (which don't compute solve state) stay valid.
    solved: bool = False
    solve_count: int = 0
    created_at: datetime
