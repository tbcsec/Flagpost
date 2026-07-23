"""Site-admin overview schema (Admin → Dashboard).

A cross-competition consolidation view (§6.3) — the only sanctioned read that
spans every competition — for a global Administrator to see platform totals and
each competition's status + health at a glance. Gated on ``view_global_analytics``.
"""

from datetime import datetime

from pydantic import BaseModel


class CompetitionHealth(BaseModel):
    id: str
    name: str
    # "draft" | "scheduled" | "running" | "ended" | "archived"
    status: str
    visibility: str
    participation_mode: str
    # Teams (team mode) or Participant-role users (individual mode).
    participants: int
    published_challenges: int
    solves: int
    open_tickets: int
    created_at: datetime


class AdminOverview(BaseModel):
    total_users: int
    active_users: int
    total_competitions: int
    active_competitions: int
    archived_competitions: int
    total_teams: int
    total_challenges: int
    published_challenges: int
    total_submissions: int
    total_solves: int
    competitions: list[CompetitionHealth]
