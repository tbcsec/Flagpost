"""Pydantic schemas for teams (kept separate from models).

Two output shapes on purpose: ``TeamOut`` is the public listing view (no
invite code), ``MyTeamOut`` is what a member sees of their own team —
including the invite code they share to bring teammates in.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


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
    created_at: datetime


class MyTeamOut(BaseModel):
    """A member's view of their own team (includes the invite code)."""

    id: str
    competition_id: str
    name: str
    invite_code: str
    members: list[TeamMemberOut]
    created_at: datetime
