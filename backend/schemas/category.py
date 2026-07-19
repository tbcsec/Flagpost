"""Pydantic schemas for challenge categories."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    competition_id: str
    name: str
    created_at: datetime
