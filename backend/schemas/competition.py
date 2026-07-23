"""Pydantic schemas for the competition entity (kept separate from models)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    mc_guess_limit: int | None = None


class CompetitionJoinRequest(BaseModel):
    """Join a competition by its invite code (any visibility)."""

    invite_code: str = Field(min_length=1, max_length=100)


class CompetitionCloneRequest(BaseModel):
    """Clone an existing competition's config under a new name."""

    name: str = Field(min_length=1, max_length=200)
