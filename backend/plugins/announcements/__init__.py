"""Announcements module (ROADMAP #14, §11.3 required-core).

Mounts the announcements router and owns the "announcements" WebSocket room: on
join a client is authorized exactly like the REST read (``challenge_view`` on
the competition) and handed the recent-announcements snapshot, and every
``announcement.published`` event is fanned out to the room as a live frame. The
router stays transport-agnostic — it emits the event; this module broadcasts it.
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

    app.include_router(announcements_router)

    async def _recent(db, competition_id: str) -> list[dict]:
        rows = (
            await db.execute(
                select(Announcement)
                .where(Announcement.competition_id == competition_id)
                .order_by(Announcement.created_at.desc())
                .limit(RECENT_LIMIT)
            )
        ).scalars()
        return [
            {
                "id": a.id,
                "competition_id": a.competition_id,
                "title": a.title,
                "body": a.body,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ]

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
            "announcements": await _recent(db, competition_id),
        }

    register_room_type("announcements", authorize=authorize, snapshot=snapshot)

    @event_bus.on("announcement.published", owner="announcements")
    async def broadcast_announcement(event_name: str, payload: dict) -> None:
        competition_id = payload.get("competition_id")
        if not competition_id:
            return
        await manager.broadcast(
            "announcements",
            competition_id,
            {
                "type": "announcement",
                "announcement": {
                    "id": payload.get("announcement_id"),
                    "competition_id": competition_id,
                    "title": payload.get("title"),
                    "body": payload.get("body"),
                    "created_at": payload.get("created_at"),
                },
            },
        )
