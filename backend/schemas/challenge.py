"""Pydantic schemas for challenges.

The flag comes **in** on create/update as plaintext (over TLS, staff-only
endpoints) and never comes back out: output schemas expose only ``has_flag``
(§13.2). There is deliberately no schema field that could carry the hash,
salt, or regex outward.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FlagType = Literal["static", "regex", "multiple_choice"]
ChallengeState = Literal["draft", "published"]
ScoringType = Literal["static", "dynamic"]

# A multiple-choice option list: 2–10 options, each a short string.
Choices = list[str]


class ChallengeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: dict[str, Any] = Field(default_factory=dict)
    category_id: str | None = None
    points: int = Field(default=100, ge=0, le=100_000)
    # Scoring model. For "dynamic", min_points + decay are required and
    # min_points must not exceed points (validated in the router).
    scoring_type: ScoringType = "static"
    min_points: int | None = Field(default=None, ge=0, le=100_000)
    decay: int | None = Field(default=None, ge=1, le=100_000)
    # Scheduled release: hidden from competitors until this time (Phase 9).
    release_at: datetime | None = None
    # Unlock chain: challenge ids that must be solved first (Phase 9).
    prerequisites: list[str] = Field(default_factory=list, max_length=50)
    # Metadata from the competition's managed vocab (Phase 9).
    tags: list[str] = Field(default_factory=list, max_length=50)
    difficulty: str | None = Field(default=None, max_length=50)
    flag_type: FlagType = "static"
    case_insensitive: bool = False
    # Plaintext flag (static), pattern (regex), or the **correct option**
    # (multiple_choice); optional so drafts can be sketched before the flag
    # exists. Publishing requires one.
    flag: str | None = Field(default=None, min_length=1, max_length=500)
    # The options shown for a multiple_choice challenge (the correct one is
    # `flag`, and must appear here). Ignored for other flag types.
    choices: Choices | None = Field(default=None, min_length=2, max_length=10)


class ResetGuessesRequest(BaseModel):
    """Reset multiple-choice guesses. Both null = a challenge-wide (bulk) reset;
    exactly one = a targeted reset for that team (team-mode) or user (individual)."""

    user_id: str | None = None
    team_id: str | None = None


class ChallengeSolver(BaseModel):
    """One subject that solved a challenge (the "who solved this" list). Ordered
    earliest-first; the earliest is the first blood."""

    subject_id: str
    name: str
    solved_at: datetime
    is_first_blood: bool


class ChallengeUpdate(BaseModel):
    """PATCH body — only provided fields are applied. Sending ``flag`` (with
    ``flag_type``/``case_insensitive``/``choices`` as needed) replaces the stored flag."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: dict[str, Any] | None = None
    category_id: str | None = None
    points: int | None = Field(default=None, ge=0, le=100_000)
    scoring_type: ScoringType | None = None
    min_points: int | None = Field(default=None, ge=0, le=100_000)
    decay: int | None = Field(default=None, ge=1, le=100_000)
    release_at: datetime | None = None
    prerequisites: list[str] | None = Field(default=None, max_length=50)
    tags: list[str] | None = Field(default=None, max_length=50)
    difficulty: str | None = Field(default=None, max_length=50)
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
    # ``points`` is the configured value (the *initial* worth for dynamic
    # challenges); ``value`` is what it's worth right now given its solve count
    # (equal to ``points`` for static, decayed for dynamic). Cards show ``value``.
    points: int
    scoring_type: ScoringType = "static"
    min_points: int | None = None
    decay: int | None = None
    value: int = 0
    # Scheduled release time; null = released on publish. Competitors never see a
    # challenge before this, so when they can read one it's always released.
    release_at: datetime | None = None
    # Unlock chain: the prerequisite challenge ids, and whether this challenge is
    # currently locked for the requesting subject (any prerequisite unsolved).
    # Staff always see locked=False. Defaulted for create/update/publish responses.
    prerequisites: list[str] = []
    locked: bool = False
    tags: list[str] = []
    difficulty: str | None = None
    state: ChallengeState
    flag_type: FlagType

    @field_validator("prerequisites", "tags", mode="before")
    @classmethod
    def _list_default(cls, v: object) -> list:
        # These columns are nullable (None = empty) → normalize to [].
        return v or []
    case_insensitive: bool
    has_flag: bool  # the only flag-related fact that ever leaves the server
    # The multiple-choice options a competitor picks from (the correct one is NOT
    # revealed). Null for static/regex challenges.
    choices: Choices | None = None
    # Guesses left for the requesting subject on a multiple_choice challenge under
    # the competition-wide cap. Null = no limit (or not multiple-choice). Computed
    # on the detail read; left None on create/update/publish responses.
    attempts_remaining: int | None = None
    # The multiple-choice challenge's *current worth for the requesting subject*
    # after their wrong guesses so far, under the competition's wrong-guess penalty
    # (#148). Null unless a penalty is active and has already reduced it below
    # ``value`` (i.e. not multiple-choice, penalty off, no wrong guesses yet, or
    # already solved). Lets a competitor see the reduced stakes before solving.
    subject_value: int | None = None
    # The requesting user's own 1–5 rating of this challenge, or null if they
    # haven't rated it (drives the post-solve rating prompt). Only competitors rate.
    my_rating: int | None = None
    # Solve state (Phase 6). ``solved`` is relative to the requesting subject —
    # the team (team-mode) or user (individual-mode); false for a viewer with no
    # subject (e.g. a manager not on a team). ``solve_count`` is the number of
    # distinct subjects that have solved it. Defaulted so the create/update/
    # publish responses (which don't compute solve state) stay valid.
    solved: bool = False
    solve_count: int = 0
    created_at: datetime
