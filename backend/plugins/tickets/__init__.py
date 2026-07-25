"""Support Tickets module (ROADMAP #18, §4.4, §11.3 required-core).

Mounts the ticket routes and owns two WebSocket rooms (§4.1):

- ``ticket/<ticket_id>`` — the live thread. Authorized to the opener and to
  staff; each new message pushes a lightweight ping so clients refetch the
  (permission-filtered) thread. Bodies aren't broadcast, so internal notes can't
  leak to a competitor watching the room.
- ``support/<competition_id>`` — the staff queue. Authorized to
  ``ticket_assign`` holders; new/assigned/resolved tickets push a ping.

Clients turn an incoming message ping they didn't author into the §4.4 audio
cue. The router stays transport-agnostic — it emits the §3.2 events; this module
broadcasts them.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from auth.deps import user_has_permission
    from models.competition import Competition
    from models.ticket import Ticket
    from realtime import manager, register_room_type
    from routers.tickets import router as tickets_router

    app.include_router(tickets_router)

    async def authorize_ticket(db, user, ticket_id: str) -> bool:
        ticket = await db.get(Ticket, ticket_id)
        if ticket is None:
            return False
        if ticket.opener_user_id == user.id:
            return True
        return await user_has_permission(
            db, user.id, "ticket_assign", ticket.competition_id
        )

    async def authorize_support(db, user, competition_id: str) -> bool:
        if await db.get(Competition, competition_id) is None:
            return False
        return await user_has_permission(
            db, user.id, "ticket_assign", competition_id
        )

    async def ticket_presence_member(db, user, ticket_id: str, mode: str) -> dict:
        # Role drives the "a judge is looking at this ticket" hint on the thread:
        # staff (ticket_assign) vs the participant who opened it.
        ticket = await db.get(Ticket, ticket_id)
        is_staff = ticket is not None and await user_has_permission(
            db, user.id, "ticket_assign", ticket.competition_id
        )
        return {
            "id": user.id,
            "name": user.display_name,
            "role": "staff" if is_staff else "participant",
            "mode": mode,
        }

    register_room_type(
        "ticket", authorize=authorize_ticket, presence_member=ticket_presence_member
    )
    register_room_type("support", authorize=authorize_support)

    @event_bus.on("ticket.created", owner="tickets")
    async def on_created(event_name: str, payload: dict) -> None:
        competition_id = payload.get("competition_id")
        if competition_id:
            await manager.broadcast(
                "support",
                competition_id,
                {"type": "ticket_created", "ticket_id": payload.get("ticket_id")},
            )

    @event_bus.on("ticket.message_posted", owner="tickets")
    async def on_message(event_name: str, payload: dict) -> None:
        ticket_id = payload.get("ticket_id")
        if ticket_id:
            # No body in the frame — clients refetch the permission-filtered
            # thread, so an internal note never reaches a competitor's socket.
            await manager.broadcast(
                "ticket",
                ticket_id,
                {
                    "type": "ticket_message",
                    "ticket_id": ticket_id,
                    "author_user_id": payload.get("author_user_id"),
                    "is_internal": payload.get("is_internal", False),
                },
            )
        # Thread activity also bumps the staff queue (#18): without this, a
        # reply never refreshes the support view until the ticket resolves.
        # ticket_updated (not ticket_created) so no audio cue fires.
        competition_id = payload.get("competition_id")
        if competition_id:
            await manager.broadcast(
                "support",
                competition_id,
                {"type": "ticket_updated", "ticket_id": ticket_id},
            )

    async def _broadcast_update(payload: dict) -> None:
        competition_id = payload.get("competition_id")
        ticket_id = payload.get("ticket_id")
        frame = {"type": "ticket_updated", "ticket_id": ticket_id}
        if ticket_id:
            await manager.broadcast("ticket", ticket_id, frame)
        if competition_id:
            await manager.broadcast("support", competition_id, frame)

    @event_bus.on("ticket.assigned", owner="tickets")
    async def on_assigned(event_name: str, payload: dict) -> None:
        await _broadcast_update(payload)

    @event_bus.on("ticket.resolved", owner="tickets")
    async def on_resolved(event_name: str, payload: dict) -> None:
        await _broadcast_update(payload)
