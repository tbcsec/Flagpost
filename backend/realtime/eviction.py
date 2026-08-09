"""Server-driven WebSocket revocation (#10).

Room authorization runs once, at the handshake — so a socket a user already holds
survives when their access is revoked mid-session (a soft-ban, an account
deletion, or removal from a team). These listeners close the affected sockets
when the corresponding events fire, restoring the bound the handshake ban-check
only promises for *new* connections. Registered on the background lane (ADR-0012):
the work is a socket close, never a DB touch, and must not block the emitting
request.
"""

from __future__ import annotations

import logging

from realtime.manager import manager

logger = logging.getLogger("realtime")


def register_ws_eviction(event_bus) -> None:
    async def _on_user_revoked(event_name: str, payload: dict) -> None:
        user_id = payload.get("user_id")
        if not user_id:
            return
        closed = await manager.close_user_sockets(user_id)
        if closed:
            logger.info("evicted %d websocket(s) for user %s", closed, user_id)

    async def _on_team_member_left(event_name: str, payload: dict) -> None:
        user_id = payload.get("user_id")
        team_id = payload.get("team_id")
        if not user_id or not team_id:
            return
        # Only the removed team's scratchpad docs (doc_key team_challenge:<team_id>:*);
        # the member keeps their other rooms (scoreboard, tickets, other teams).
        await manager.close_user_sockets(
            user_id,
            room_type="note",
            room_id_prefix=f"team_challenge:{team_id}:",
        )

    event_bus.subscribe("user.banned", _on_user_revoked, background=True)
    event_bus.subscribe("user.deleted", _on_user_revoked, background=True)
    event_bus.subscribe("team.member_left", _on_team_member_left, background=True)
