"""Pydantic schemas for teams (kept separate from models).

Two output shapes on purpose: ``TeamOut`` is the public listing view (no
invite code), ``MyTeamOut`` is what a member sees of their own team —
including the invite code they share to bring teammates in.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    affiliation: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=200)
    approval_required: bool = False


class TeamUpdate(BaseModel):
    """Captain-editable team profile (PATCH — only provided fields apply)."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    affiliation: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=200)
    approval_required: bool | None = None


class TeamApplicationOut(BaseModel):
    id: str
    user_id: str
    display_name: str
    created_at: datetime


class TeamJoinRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=64)


class TeamMemberOut(BaseModel):
    user_id: str
    display_name: str
    is_captain: bool


class TeamOut(BaseModel):
    """Public view — safe for any authenticated user in the competition."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    competition_id: str
    name: str
    member_count: int
    affiliation: str | None = None
    country: str | None = None
    website: str | None = None
    created_at: datetime


class MyTeamOut(BaseModel):
    """A member's view of their own team (includes the invite code)."""

    id: str
    competition_id: str
    name: str
    invite_code: str
    members: list[TeamMemberOut]
    affiliation: str | None = None
    country: str | None = None
    website: str | None = None
    approval_required: bool = False
    created_at: datetime


class TeamJoinResult(BaseModel):
    """Joining an open team returns the team; an approval-required one returns
    ``pending`` with no team until the captain approves."""

    pending: bool
    team: MyTeamOut | None = None
