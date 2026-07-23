"""Bracket selection schemas (Phase 9, Group C)."""

from pydantic import BaseModel, Field


class BracketOut(BaseModel):
    bracket: str | None = None


class BracketSet(BaseModel):
    # Null/blank clears the choice; otherwise validated against the vocab.
    bracket: str | None = Field(default=None, max_length=50)


class BracketSetForSubject(BracketSet):
    pass
