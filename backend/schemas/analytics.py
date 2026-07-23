"""Pydantic schemas for challenge & team analytics (ROADMAP #23)."""

from datetime import datetime

from pydantic import BaseModel


class ChallengeAnalytics(BaseModel):
    challenge_id: str
    title: str
    category: str | None
    points: int
    state: str
    solve_count: int
    attempt_count: int
    fail_count: int
    completion_rate: float  # solves / scoring subjects, 0..1
    avg_solve_time_seconds: float | None  # null when unsolved
    hints_used: int
    ticket_count: int
    avg_rating: float | None  # null when the challenge has no ratings yet
    rating_count: int


class ChallengeAnalyticsOut(BaseModel):
    mode: str  # "team" | "individual"
    subject_count: int
    challenges: list[ChallengeAnalytics]


class TeamAnalytics(BaseModel):
    subject_id: str
    name: str
    rank: int
    points: int
    solve_count: int
    first_bloods: int
    ticket_count: int
    last_solve_at: datetime | None


class TeamAnalyticsOut(BaseModel):
    mode: str
    teams: list[TeamAnalytics]
