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


class SkillMatrixUser(BaseModel):
    user_id: str
    display_name: str
    # skill name -> cumulative score. Missing keys are 0 (not every user solves
    # every category); the frontend fills the grid against the shared ``skills`` axis.
    scores: dict[str, int]
    total: int


class SkillMatrixOut(BaseModel):
    """Every user × skill (``GET /api/admin/skills``), paginated over users."""

    # The shared axis (matrix columns) — the union of skills across all users.
    skills: list[str]
    users: list[SkillMatrixUser]
    total_users: int
    limit: int
    offset: int
