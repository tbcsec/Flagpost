"""Pydantic schemas for in-app notifications (ARCHITECTURE.md §4.4)."""

from datetime import datetime

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    body: str | None
    link: str | None
    competition_id: str | None
    # Derived from the model's nullable ``read_at`` — null means unread.
    read: bool
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int
