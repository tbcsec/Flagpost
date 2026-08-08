"""Pydantic schemas for the competition entity (kept separate from models)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ParticipationMode = Literal["team", "individual"]
Visibility = Literal["public", "private"]


class CompetitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    start_at: datetime | None = None
    end_at: datetime | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    participation_mode: ParticipationMode = "team"
    visibility: Visibility = "private"
    # Competition-wide cap on guesses per subject per multiple-choice challenge.
    # Defaults to 2; send an explicit null for unlimited.
    mc_guess_limit: int | None = Field(default=2, ge=1, le=1000)
    # Percent of a multiple-choice challenge's value docked per wrong guess (#148).
    # 1–100; null = off. Defaults off — enabling it is an explicit opt-in.
    mc_penalty_pct: int | None = Field(default=None, ge=1, le=100)
    challenge_ratings_enabled: bool = False
    # Managed vocab challenges may use (Phase 9).
    challenge_tags: list[str] = Field(default_factory=list, max_length=100)
    difficulty_tiers: list[str] = Field(default_factory=list, max_length=20)
    # Public spectator board + CTFtime feed opt-ins (Phase 9).
    public_scoreboard: bool = False
    ctftime_enabled: bool = False
    # Brackets/divisions competitors self-select at join (Phase 9).
    brackets: list[str] = Field(default_factory=list, max_length=20)
    # Max members per team (team-mode); null = unlimited.
    max_team_size: int | None = Field(default=None, ge=1, le=1000)
    # Halt gameplay (competitors can't submit flags); staff still can.
    paused: bool = False
    # Per-competition rules / code-of-conduct override (#57); null = use the
    # site-wide document. Rich-text (ProseMirror JSON), like a challenge
    # description.
    rules_override: dict[str, Any] | None = None
    rules_display_only: bool = False


class CompetitionUpdate(BaseModel):
    """PATCH body — every field optional; only provided fields are applied."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    start_at: datetime | None = None
    end_at: datetime | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    participation_mode: ParticipationMode | None = None
    visibility: Visibility | None = None
    # Set to null to remove the cap. (exclude_unset means an omitted field is
    # left unchanged; an explicit null clears it.)
    mc_guess_limit: int | None = Field(default=None, ge=1, le=1000)
    # Null clears the penalty (off); 1–100 sets it. Omitted = unchanged.
    mc_penalty_pct: int | None = Field(default=None, ge=1, le=100)
    challenge_ratings_enabled: bool | None = None
    challenge_tags: list[str] | None = Field(default=None, max_length=100)
    difficulty_tiers: list[str] | None = Field(default=None, max_length=20)
    public_scoreboard: bool | None = None
    ctftime_enabled: bool | None = None
    brackets: list[str] | None = Field(default=None, max_length=20)
    max_team_size: int | None = Field(default=None, ge=1, le=1000)
    paused: bool | None = None
    # Explicit null clears the override (falls back to the site-wide rules);
    # a new/changed non-null value forces re-acceptance (see the router).
    rules_override: dict[str, Any] | None = None
    rules_display_only: bool | None = None


class CompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    start_at: datetime | None
    end_at: datetime | None
    registration_opens_at: datetime | None
    registration_closes_at: datetime | None
    participation_mode: ParticipationMode
    visibility: Visibility
    # Only members/organisers ever receive a CompetitionOut (visibility is
    # enforced on read), and it mirrors the team invite-code exposure, so the
    # code travels with the record for organisers to share.
    invite_code: str
    created_at: datetime
    archived_at: datetime | None = None
    # When the retention job will hard-delete this archived competition (#26);
    # null = no clock (active, retention off, or archived before the feature).
    purge_after: datetime | None = None
    mc_guess_limit: int | None = None
    mc_penalty_pct: int | None = None
    challenge_ratings_enabled: bool = False
    challenge_tags: list[str] = Field(default_factory=list)
    difficulty_tiers: list[str] = Field(default_factory=list)
    public_scoreboard: bool = False
    ctftime_enabled: bool = False
    brackets: list[str] = Field(default_factory=list)
    max_team_size: int | None = None
    paused: bool = False
    rules_override: dict[str, Any] | None = None
    rules_display_only: bool = False

    @field_validator("challenge_tags", "difficulty_tiers", "brackets", mode="before")
    @classmethod
    def _vocab_default(cls, v: object) -> list:
        return v or []


class CompetitionJoinRequest(BaseModel):
    """Join a competition by its invite code (any visibility).

    ``accept_rules`` lets the joiner accept the competition's rules in the same
    request: the code path can't pre-fetch the rules (the competition id isn't
    known until the code resolves, and a private competition's existence isn't
    disclosed), so the flow is join → 403 carrying the rules document → re-join
    with ``accept_rules=true``. The valid invite code is the authorization.
    """

    invite_code: str = Field(min_length=1, max_length=100)
    accept_rules: bool = False


class CompetitionCloneRequest(BaseModel):
    """Clone an existing competition's config under a new name."""

    name: str = Field(min_length=1, max_length=200)
