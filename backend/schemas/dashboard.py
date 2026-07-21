"""Pydantic schemas for the operational dashboard (ROADMAP #16, §10).

Each widget fetches its own slice of data (§10.1), so the dashboard is a set of
small read shapes rather than one monolithic payload.
"""

from datetime import datetime

from pydantic import BaseModel


class DashboardStats(BaseModel):
    """Competition-wide aggregate counts for the manager stat tiles."""

    total_solves: int
    total_submissions: int
    active_participants: int  # teams (team mode) or participants (individual)
    published_challenges: int
    recent_solves_1h: int


class RecentSolve(BaseModel):
    subject_name: str  # team name (team mode) or display name (individual)
    challenge_title: str
    points: int
    at: datetime


class ChallengeHealth(BaseModel):
    challenge_id: str
    title: str
    points: int
    solves: int  # distinct solving subjects
    attempts: int  # all submissions, right or wrong


class MyStanding(BaseModel):
    """The requesting subject's own standing — null when they have no subject."""

    rank: int | None
    points: int | None
    solved_count: int
