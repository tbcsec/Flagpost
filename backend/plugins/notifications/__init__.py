"""In-App Notifications module (ARCHITECTURE.md §4.4, §11.3 required-core).

Owns the per-user ``/ws/user/<user_id>`` room and the baseline notification
center. Turns the required-core ticket events (§3.2) into per-user
notifications, routed the same way the §4.4 audio cue is — a new ticket
notifies staff; a reply notifies whichever side didn't post; a resolve notifies
the opener — so the bell and the sound tell the same story. Delivery goes
through :mod:`utils.notifications`, the shared path the automation ``notify``
action reuses in Phase 1.

Notification handlers run **foreground** (the ADR-0012 default): a notification
is a fast local write + in-process WS fan-out, so awaiting it keeps the row
committed before the mutation's response returns and keeps tests deterministic.
The background lane is for the slow/external handlers (webhooks, email) that
arrive with the automation engine.
"""

from __future__ import annotations

# Deep link target for ticket notifications. The support page reads the active
# competition from the client store, so a bare path is right here (the
# notification still carries competition_id for context/filtering).
_SUPPORT_LINK = "/support"


def setup(app, event_bus, db_factory) -> None:
    from auth.deps import user_has_permission, users_with_permission
    from models.ticket import Ticket
    from realtime import register_room_type
    from routers.notifications import router as notifications_router
    from utils.notifications import broadcast_notifications, create_notifications

    app.include_router(notifications_router)

    async def authorize_user_room(db, user, room_id: str) -> bool:
        # A private per-user room: only its owner may join (§4.4). No presence —
        # a notification stream isn't a shared resource like a challenge/ticket.
        return user.id == room_id

    register_room_type("user", authorize=authorize_user_room)

    async def _deliver(
        db,
        recipients,
        *,
        type: str,
        title: str,
        body: str | None = None,
        competition_id: str | None = None,
    ) -> None:
        """Create + commit + broadcast to a resolved recipient set."""
        made = await create_notifications(
            db,
            recipients,
            type=type,
            title=title,
            body=body,
            link=_SUPPORT_LINK,
            competition_id=competition_id,
        )
        if not made:
            return
        await db.commit()
        await broadcast_notifications(made)

    @event_bus.on("ticket.created", owner="notifications")
    async def on_ticket_created(event_name: str, payload: dict) -> None:
        competition_id = payload.get("competition_id")
        ticket_id = payload.get("ticket_id")
        opener = payload.get("opener_user_id")
        if not competition_id or not ticket_id:
            return
        async with db_factory() as db:
            staff = await users_with_permission(db, "ticket_assign", competition_id)
            staff.discard(opener)  # the opener isn't notified of their own ticket
            await _deliver(
                db,
                staff,
                type="ticket.created",
                title="New support ticket",
                body=payload.get("subject"),
                competition_id=competition_id,
            )

    @event_bus.on("ticket.assigned", owner="notifications")
    async def on_ticket_assigned(event_name: str, payload: dict) -> None:
        competition_id = payload.get("competition_id")
        ticket_id = payload.get("ticket_id")
        assignee = payload.get("assignee_user_id")
        if not competition_id or not ticket_id or not assignee:
            return
        async with db_factory() as db:
            await _deliver(
                db,
                [assignee],
                type="ticket.assigned",
                title="A ticket was assigned to you",
                competition_id=competition_id,
            )

    @event_bus.on("ticket.resolved", owner="notifications")
    async def on_ticket_resolved(event_name: str, payload: dict) -> None:
        competition_id = payload.get("competition_id")
        ticket_id = payload.get("ticket_id")
        if not competition_id or not ticket_id:
            return
        async with db_factory() as db:
            ticket = await db.get(Ticket, ticket_id)
            if ticket is None:
                return
            await _deliver(
                db,
                [ticket.opener_user_id],
                type="ticket.resolved",
                title="Your ticket was resolved",
                body=ticket.subject,
                competition_id=competition_id,
            )

    @event_bus.on("ticket.message_posted", owner="notifications")
    async def on_ticket_message(event_name: str, payload: dict) -> None:
        competition_id = payload.get("competition_id")
        ticket_id = payload.get("ticket_id")
        author = payload.get("author_user_id")
        is_internal = payload.get("is_internal", False)
        if not competition_id or not ticket_id or not author:
            return
        async with db_factory() as db:
            ticket = await db.get(Ticket, ticket_id)
            if ticket is None:
                return
            author_is_staff = await user_has_permission(
                db, author, "ticket_assign", competition_id
            )
            recipients: set[str] = set()
            if author_is_staff:
                # Staff replied → notify the opener, but never surface an
                # internal note to them (mirrors the thread's own filtering).
                if not is_internal:
                    recipients.add(ticket.opener_user_id)
            elif ticket.assignee_user_id:
                # Participant replied on an assigned ticket → its assignee.
                recipients.add(ticket.assignee_user_id)
            else:
                # Unassigned → the whole staff queue.
                recipients |= await users_with_permission(
                    db, "ticket_assign", competition_id
                )
            recipients.discard(author)
            await _deliver(
                db,
                recipients,
                type="ticket.message_posted",
                title="New reply on a ticket",
                body=ticket.subject,
                competition_id=competition_id,
            )
