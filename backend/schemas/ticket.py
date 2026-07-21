"""Pydantic schemas for support tickets (ROADMAP #18)."""

from datetime import datetime

from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    challenge_id: str | None = None


class TicketReply(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    # Staff-only note; setting this requires ticket_view_internal_notes.
    is_internal: bool = False


class TicketAssign(BaseModel):
    # None assigns the ticket to the acting staff member.
    assignee_user_id: str | None = None


class TicketMessageOut(BaseModel):
    id: str
    author_user_id: str
    author_name: str
    body: str
    is_internal: bool
    created_at: datetime


class TicketOut(BaseModel):
    """Summary row for the ticket list."""

    id: str
    subject: str
    status: str
    challenge_id: str | None
    challenge_title: str | None
    opener_name: str
    team_name: str | None
    assignee_name: str | None
    message_count: int
    created_at: datetime


class TicketDetail(TicketOut):
    """A single ticket plus its (permission-filtered) thread."""

    messages: list[TicketMessageOut]
