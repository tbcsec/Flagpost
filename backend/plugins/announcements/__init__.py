"""Announcements module (ROADMAP #14, §11.3 required-core).

Mounts the announcements router and owns the "announcements" WebSocket room: on
join a client is authorized exactly like the REST read (``challenge_view`` on
the competition) and handed the recent-announcements snapshot. The router stays
transport-agnostic — it emits ``announcement.published``; this module delivers.

Delivery has two lanes (#40), because the shared room fans a frame to *every*
connected member:

- **audience "all"** — the cheap path: broadcast the announcement to the shared
  room, plus one bell notification per member.
- **targeted** — never touches the shared room (that would leak the body to the
  whole competition while merely *looking* targeted). Recipients are resolved
  and reached over their own ``/ws/user/<id>`` rooms, which the notification
  frame already rides; their clients then refetch the server-filtered list.

Either way the join snapshot is audience-filtered too, so a reconnect can't
reveal what the live path withheld. Audience rules live in ``utils/announcements``.
"""

from __future__ import annotations

RECENT_LIMIT = 20


def setup(app, event_bus, db_factory) -> None:
    from sqlalchemy import select

    from auth.deps import user_has_permission
    from models.announcement import Announcement
    from models.competition import Competition
    from realtime import manager, register_room_type
    from routers.announcements import router as announcements_router
    from utils.announcements import (
        resolve_recipients,
        user_team_ids,
        visible_to_user,
    )
    from utils.notifications import broadcast_notifications, create_notifications

    app.include_router(announcements_router)

    def _frame(a: Announcement) -> dict:
        return {
            "id": a.id,
            "competition_id": a.competition_id,
            "title": a.title,
            "body": a.body,
            "severity": a.severity,
            "audience_type": a.audience_type,
            "created_at": a.created_at.isoformat(),
        }

    async def _recent(db, user, competition_id: str) -> list[dict]:
        rows = list(
            (
                await db.execute(
                    select(Announcement)
                    .where(
                        Announcement.competition_id == competition_id,
                        # The live feed is published-only — a scheduled draft
                        # (#349) must not ride the reconnect snapshot, or it would
                        # surface before its publish_at.
                        Announcement.hidden.is_(False),
                    )
                    .order_by(Announcement.created_at.desc())
                    .limit(RECENT_LIMIT)
                )
            ).scalars()
        )
        # Same audience gate as the REST read — a snapshot must not hand a
        # reconnecting client an announcement it was never targeted with.
        is_staff = await user_has_permission(
            db, user.id, "announcement_create", competition_id
        )
        if not is_staff:
            team_ids = await user_team_ids(db, competition_id, user.id)
            rows = [
                a
                for a in rows
                if visible_to_user(
                    a, user_id=user.id, team_ids=team_ids, is_staff=False
                )
            ]
        return [_frame(a) for a in rows]

    async def authorize(db, user, competition_id: str) -> bool:
        if await db.get(Competition, competition_id) is None:
            return False
        return await user_has_permission(
            db, user.id, "challenge_view", competition_id
        )

    async def snapshot(db, user, competition_id: str) -> dict:
        return {
            "type": "announcements",
            "competition_id": competition_id,
            "announcements": await _recent(db, user, competition_id),
        }

    register_room_type("announcements", authorize=authorize, snapshot=snapshot)

    # Background lane (#176, ADR-0012): fan-out is per-recipient row creation +
    # WS sends, which for an all-participants announcement was a 24s foreground
    # block on the POST. The Announcement row itself is committed by the route
    # before this event is emitted, so it stays durable; only the per-user
    # notification rows + WS delivery are deferred (best-effort, ms later).
    @event_bus.on("announcement.published", owner="announcements", background=True)
    async def deliver_announcement(event_name: str, payload: dict) -> None:
        competition_id = payload.get("competition_id")
        announcement_id = payload.get("announcement_id")
        if not competition_id or not announcement_id:
            return

        async with db_factory() as db:
            announcement = await db.get(Announcement, announcement_id)
            if announcement is None:
                return
            recipients = await resolve_recipients(db, announcement)
            # A critical announcement overrides a muted in-app category — the
            # one sanctioned bypass (§4.4), because the operator is saying
            # something the competition can't afford to miss.
            notifications = await create_notifications(
                db,
                recipients,
                type=f"announcement.{announcement.severity}",
                title=announcement.title,
                body=announcement.body,
                competition_id=competition_id,
                force=announcement.severity == "critical",
            )
            await db.commit()
            targeted = announcement.audience_type != "all"
            frame = {"type": "announcement", "announcement": _frame(announcement)}

        # Broadcast after commit, so a client refetching on the ping never sees
        # a row the transaction could still roll back.
        if not targeted:
            await manager.broadcast("announcements", competition_id, frame)
        # Targeted announcements ride the per-user notification rooms only; the
        # recipient's client turns that frame into a refetch of its filtered list.
        await broadcast_notifications(notifications)
