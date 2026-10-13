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


class SkillCell(BaseModel):
    """One user×skill cell, enriched (#435). ``weighted`` is Σ points awarded at
    solve time (decay rarity baked in — but points are per-competition vocab and
    don't normalize across events, so cross-user reads go through ``pct``);
    ``solved``/``available`` is coverage against the user's genuine opportunity
    (published challenges in their member competitions); ``pct`` is the
    percentile of ``weighted`` within this column over every tracked user."""

    weighted: int
    solved: int
    available: int
    pct: int


class SkillPopulation(BaseModel):
    """Footer aggregate for one skill column: how many tracked users have solved
    in it, and their mean weighted score — the "where is my community weak" row."""

    solvers: int
    mean_weighted: int


class SkillMatrixUser(BaseModel):
    user_id: str
    display_name: str
    # skill name -> cell. Missing keys mean an untouched category (the frontend
    # renders those against the shared ``skills`` axis as empty cells).
    scores: dict[str, SkillCell]
    # Distinct solves / Σ points awarded, across every category.
    total: int
    total_weighted: int


class SkillMatrixOut(BaseModel):
    """Every user × skill (``GET /api/admin/skills``), paginated over users."""

    # The shared axis (matrix columns) — the union of skills across all users.
    skills: list[str]
    users: list[SkillMatrixUser]
    population: dict[str, SkillPopulation]
    total_users: int
    limit: int
    offset: int
