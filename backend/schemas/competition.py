"""Pydantic schemas for the competition entity (kept separate from models)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ParticipationMode = Literal["team", "individual"]


class CompetitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    start_at: datetime | None = None
    end_at: datetime | None = None
    participation_mode: ParticipationMode = "team"


class CompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    start_at: datetime | None
    end_at: datetime | None
    participation_mode: ParticipationMode
    created_at: datetime
