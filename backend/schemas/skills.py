"""Skills web response shapes (#364, ADR-0039).

The scores are cumulative, unbounded per-skill web values (distinct solves ×
weight), keyed by normalized category name. The axis labels are explicit so the
frontend renders the same set the backend computed rather than inferring it.
"""

from pydantic import BaseModel


class SkillScore(BaseModel):
    skill: str
    score: int


class UserSkillsOut(BaseModel):
    """One user's cross-competition web (``GET /api/me/skills``)."""

    skills: list[SkillScore]
    total: int
    competitions_played: int
