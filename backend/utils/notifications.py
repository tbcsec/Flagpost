"""Notification delivery service (ARCHITECTURE.md §4.4).

One place to create + push in-app notifications, so every producer — the
ticket-event listeners in the ``notifications`` module today, the automation
engine's ``notify`` action tomorrow (Tier 3 Phase 1) — goes through the same
path rather than each hand-rolling a row + a WS frame.

Delivery is two steps the caller sequences: :func:`create_notifications`
persists the rows (add + flush, so ids/timestamps exist), the caller commits,
then :func:`broadcast_notifications` pushes each to its recipient's
``/ws/user/<user_id>`` room. Broadcasting after commit means a client that
refetches on the ping never sees a row the transaction later rolled back.
"""

from __future__ import annotations

from collections.abc import Iterable

from db import ensure_aware_utc
from models.notification import Notification
from realtime.manager import manager


async def create_notifications(
    db,
    recipients: Iterable[str],
    *,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    competition_id: str | None = None,
) -> list[Notification]:
    """Persist one notification per recipient (deduped), flushed but not committed.

    Returns the created rows so the caller can commit and then broadcast them.
    """
    made: list[Notification] = []
    for user_id in dict.fromkeys(recipients):  # dedupe, preserve order
        notification = Notification(
            user_id=user_id,
            competition_id=competition_id,
            type=type,
            title=title,
            body=body,
            link=link,
        )
        db.add(notification)
        made.append(notification)
    if made:
        await db.flush()
    return made


def notification_frame(notification: Notification) -> dict:
    """The WS frame a per-user room carries for a fresh notification."""
    return {
        "type": "notification",
        "id": notification.id,
        "notification_type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "link": notification.link,
        "read": notification.read_at is not None,
        "created_at": ensure_aware_utc(notification.created_at).isoformat(),
    }


async def broadcast_notifications(notifications: Iterable[Notification]) -> None:
    """Push each notification to its recipient's ``/ws/user/<user_id>`` room."""
    for notification in notifications:
        await manager.broadcast(
            "user", notification.user_id, notification_frame(notification)
        )
