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


class NotificationPreferences(BaseModel):
    """Per-user notification preferences (§4.4). Full set, all defaulted, so a
    PUT is a complete replacement and a GET always returns every key resolved."""

    # In-app categories — gate whether a bell notification is created at all.
    # (A `critical` announcement overrides `inapp_announcements` — §4.4, #40.)
    inapp_tickets: bool = True
    inapp_automations: bool = True
    inapp_announcements: bool = True
    # Client-honored delivery hints for the in-app notifications that are made.
    browser: bool = False
    sound: bool = True
