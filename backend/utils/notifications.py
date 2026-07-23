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

from sqlalchemy import select

from db import ensure_aware_utc
from models.notification import Notification
from models.user import User
from realtime.manager import manager

# Per-user notification preferences (§4.4). ``inapp_*`` gate *creation* of an
# in-app notification by category — honored centrally here so every producer
# (ticket listeners, the automation ``notify`` action) respects them; ``browser``
# and ``sound`` are client-honored delivery hints (the same in-app row is still
# created). A missing key resolves to its default, so an unset user gets
# everything except browser notifications (which need an explicit opt-in + an
# OS permission grant).
DEFAULT_PREFS: dict[str, bool] = {
    "inapp_tickets": True,
    "inapp_automations": True,
    "browser": False,
    "sound": True,
}


def resolve_prefs(raw: dict | None) -> dict[str, bool]:
    """Merge a stored (possibly null/partial) prefs bag over the defaults."""
    merged = dict(DEFAULT_PREFS)
    if raw:
        for key in DEFAULT_PREFS:
            if isinstance(raw.get(key), bool):
                merged[key] = raw[key]
    return merged


def inapp_key_for_type(type: str) -> str:
    """Which ``inapp_*`` preference governs a notification of this ``type``.

    Ticket events form the one distinct category a user might reasonably mute;
    everything else (chiefly automation ``notify`` actions, which carry the
    trigger event name as their type) falls under automations & alerts.
    """
    return "inapp_tickets" if type.startswith("ticket.") else "inapp_automations"


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

    Recipients who have muted this notification's category (``inapp_*``) are
    dropped before creation. Returns the created rows so the caller can commit
    and then broadcast them.
    """
    wanted = [u for u in dict.fromkeys(recipients) if u]  # dedupe, drop falsy
    if not wanted:
        return []

    # Drop recipients who've opted out of this category. A user with no stored
    # prefs (null) keeps the default (opted in), so this only ever narrows.
    key = inapp_key_for_type(type)
    rows = await db.execute(
        select(User.id, User.notification_prefs).where(User.id.in_(wanted))
    )
    prefs = {uid: resolve_prefs(raw) for uid, raw in rows}
    wanted = [u for u in wanted if prefs.get(u, DEFAULT_PREFS)[key]]

    made: list[Notification] = []
    for user_id in wanted:
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
