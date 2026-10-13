"""Skills web response shapes (#364, ADR-0039).

The scores are cumulative, unbounded per-skill web values (distinct solves ×
weight), keyed by normalized category name. The axis labels are explicit so the
frontend renders the same set the backend computed rather than inferring it.
"""

from datetime import datetime

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
    # v2 (#440): efficiency + elite signals. Counts, not ratios — the frontend
    # derives attempts/hints *per solve* so the payload stays integers.
    attempts: int
    hints: int
    first_bloods: int


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


class AdminUserSkillRow(BaseModel):
    """One skill in the admin drill-down (#440) — the matrix cell's signals
    rolled up per category for one user, attempts including never-solved
    struggle."""

    skill: str
    weighted: int
    solved: int
    attempts: int
    hints: int
    first_bloods: int


class AdminUserSolve(BaseModel):
    challenge_title: str
    competition_name: str
    skill: str
    points_awarded: int
    attempts: int
    hints: int
    first_blood: bool
    solved_at: datetime


class AdminUserSkillsOut(BaseModel):
    """The admin drill-down (``GET /api/admin/skills/users/{user_id}``):
    per-skill stats plus the recent solve rows (capped at 200, newest first)."""

    user_id: str
    display_name: str
    skills: list[AdminUserSkillRow]
    solves: list[AdminUserSolve]
    total: int
    total_weighted: int
