"""In-process WebSocket connection manager (ARCHITECTURE.md §4.1).

Rooms are keyed ``(room_type, room_id)`` — e.g. ``("scoreboard", <competition
id>)`` — mirroring the ``wss://…/ws/<type>/<id>`` URL shape. The manager only
tracks membership and fans out JSON frames; *who may join a room* is decided by
the room's registered authorizer (see ``realtime.router``), never here.

Single-process by design: like the event bus (ADR-0005), this does not fan out
across backend instances. Acceptable for the docker-compose deployment model;
the seam to revisit for horizontal scaling is Redis pub/sub behind this same
interface.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("realtime")


@dataclass
class _PresenceMember:
    """A single user present in a room (§4.1 payload: id, name, role, mode).

    Deduped per user id — a user with several tabs open counts once, and only
    drops from the room when their *last* socket goes (``sockets`` empty).
    """

    payload: dict[str, Any]
    sockets: set[WebSocket] = field(default_factory=set)


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[tuple[str, str], set[WebSocket]] = defaultdict(set)
        # Presence set per room: room key → {user_id → member}. Distinct from
        # ``_rooms`` (socket membership) because presence is deduped per user
        # and cleared on a debounce, not the instant a socket drops.
        self._presence: dict[tuple[str, str], dict[str, _PresenceMember]] = (
            defaultdict(dict)
        )
        # Pending debounced-clear tasks, keyed (room_type, room_id, user_id), so
        # a reconnect inside the grace window can cancel the impending removal.
        self._expiries: dict[tuple[str, str, str], asyncio.Task] = {}
        # Reverse indexes for server-driven eviction (#10): a user's open sockets,
        # and each socket's owner + room (one room per socket). Handshake-time
        # authorization can't drop a socket the user already holds when their
        # access is revoked mid-session; these let a ban/removal close it.
        self._user_sockets: dict[str, set[WebSocket]] = defaultdict(set)
        self._socket_meta: dict[WebSocket, tuple[str, str, str]] = {}

    def join(
        self, room_type: str, room_id: str, websocket: WebSocket, user_id: str
    ) -> None:
        self._rooms[(room_type, room_id)].add(websocket)
        self._user_sockets[user_id].add(websocket)
        self._socket_meta[websocket] = (user_id, room_type, room_id)

    def leave(self, room_type: str, room_id: str, websocket: WebSocket) -> None:
        room = self._rooms.get((room_type, room_id))
        if room is not None:
            room.discard(websocket)
            if not room:
                del self._rooms[(room_type, room_id)]
        meta = self._socket_meta.pop(websocket, None)
        if meta is not None:
            socks = self._user_sockets.get(meta[0])
            if socks is not None:
                socks.discard(websocket)
                if not socks:
                    del self._user_sockets[meta[0]]

    async def close_user_sockets(
        self,
        user_id: str,
        *,
        room_type: str | None = None,
        room_id_prefix: str | None = None,
        code: int = 4403,
    ) -> int:
        """Force-close a user's open sockets — server-driven revocation (#10).

        Optionally filter to one ``room_type`` and/or a ``room_id`` prefix (used
        to target only a removed team's scratchpad docs). Returns the count
        closed. The socket's own receive loop then unwinds and calls ``leave``,
        which clears the indexes; closing here doesn't mutate them, so a slow
        unwind can't corrupt state.
        """
        closed = 0
        for websocket in list(self._user_sockets.get(user_id, ())):
            meta = self._socket_meta.get(websocket)
            if meta is None:
                continue
            _uid, rt, rid = meta
            if room_type is not None and rt != room_type:
                continue
            if room_id_prefix is not None and not rid.startswith(room_id_prefix):
                continue
            try:
                await websocket.close(code=code)
            except Exception:  # noqa: BLE001 — already gone is fine
                pass
            closed += 1
        return closed

    def room_size(self, room_type: str, room_id: str) -> int:
        return len(self._rooms.get((room_type, room_id), ()))

    async def broadcast(
        self,
        room_type: str,
        room_id: str,
        message: dict[str, Any],
        *,
        exclude: WebSocket | None = None,
    ) -> None:
        """Send ``message`` as JSON to every socket in the room.

        ``exclude`` skips one socket — used by the CRDT relay (§4.2) so a client
        doesn't receive an echo of the update it just sent. A socket that fails
        to send (client vanished mid-broadcast) is dropped from the room rather
        than failing the broadcast for its neighbours.
        """
        dead: list[WebSocket] = []
        for websocket in list(self._rooms.get((room_type, room_id), ())):
            if websocket is exclude:
                continue
            try:
                await websocket.send_json(message)
            except Exception:  # noqa: BLE001 — any send failure means "gone"
                dead.append(websocket)
        for websocket in dead:
            self.leave(room_type, room_id, websocket)
            logger.debug("dropped dead socket from %s/%s", room_type, room_id)

    # --- Presence (§4.1) --------------------------------------------------
    #
    # Presence is WS-level state, not an event-bus event: a room type opts in
    # by registering a presence-member builder (see ``realtime.router``), and
    # the manager tracks who's in the room and fans out the full set on change.

    def presence_members(self, room_type: str, room_id: str) -> list[dict[str, Any]]:
        """The current presence set for a room, ordered by display name."""
        members = self._presence.get((room_type, room_id))
        if not members:
            return []
        return [
            m.payload
            for m in sorted(
                members.values(), key=lambda m: m.payload.get("name", "")
            )
        ]

    def _presence_frame(self, room_type: str, room_id: str) -> dict[str, Any]:
        return {
            "type": "presence",
            "members": self.presence_members(room_type, room_id),
        }

    async def presence_join(
        self, room_type: str, room_id: str, websocket: WebSocket, member: dict[str, Any]
    ) -> None:
        """Add ``websocket`` to the room's presence set under ``member['id']``.

        Cancels any pending debounced removal for that user (a reconnect inside
        the grace window), then broadcasts the refreshed set to the room.
        """
        user_id = member["id"]
        pending = self._expiries.pop((room_type, room_id, user_id), None)
        if pending is not None:
            pending.cancel()

        members = self._presence[(room_type, room_id)]
        existing = members.get(user_id)
        if existing is None:
            members[user_id] = _PresenceMember(payload=member, sockets={websocket})
        else:
            existing.sockets.add(websocket)
        await self.broadcast(
            room_type, room_id, self._presence_frame(room_type, room_id)
        )

    async def presence_leave(
        self,
        room_type: str,
        room_id: str,
        websocket: WebSocket,
        user_id: str,
        grace_seconds: float,
    ) -> None:
        """Drop ``websocket`` from the user's presence entry.

        If it was the user's last socket, schedule a debounced removal after
        ``grace_seconds`` rather than clearing instantly, so a brief reconnect
        doesn't flicker the "who's here" list (§4.1).
        """
        members = self._presence.get((room_type, room_id))
        if not members:
            return
        member = members.get(user_id)
        if member is None:
            return
        member.sockets.discard(websocket)
        if member.sockets:
            return  # another tab keeps the user present

        ekey = (room_type, room_id, user_id)
        pending = self._expiries.pop(ekey, None)
        if pending is not None:
            pending.cancel()
        self._expiries[ekey] = asyncio.ensure_future(
            self._expire_member(room_type, room_id, user_id, grace_seconds)
        )

    async def _expire_member(
        self, room_type: str, room_id: str, user_id: str, grace_seconds: float
    ) -> None:
        try:
            await asyncio.sleep(grace_seconds)
        except asyncio.CancelledError:
            return
        self._expiries.pop((room_type, room_id, user_id), None)
        members = self._presence.get((room_type, room_id))
        if not members:
            return
        member = members.get(user_id)
        if member is None or member.sockets:
            return  # rejoined during the grace window
        del members[user_id]
        if not members:
            del self._presence[(room_type, room_id)]
        await self.broadcast(
            room_type, room_id, self._presence_frame(room_type, room_id)
        )


# Module-level singleton, like the event bus (§3.1).
manager = ConnectionManager()
