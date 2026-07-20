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

import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("realtime")


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[tuple[str, str], set[WebSocket]] = defaultdict(set)

    def join(self, room_type: str, room_id: str, websocket: WebSocket) -> None:
        self._rooms[(room_type, room_id)].add(websocket)

    def leave(self, room_type: str, room_id: str, websocket: WebSocket) -> None:
        room = self._rooms.get((room_type, room_id))
        if room is None:
            return
        room.discard(websocket)
        if not room:
            del self._rooms[(room_type, room_id)]

    def room_size(self, room_type: str, room_id: str) -> int:
        return len(self._rooms.get((room_type, room_id), ()))

    async def broadcast(
        self, room_type: str, room_id: str, message: dict[str, Any]
    ) -> None:
        """Send ``message`` as JSON to every socket in the room.

        A socket that fails to send (client vanished mid-broadcast) is dropped
        from the room rather than failing the broadcast for its neighbours.
        """
        dead: list[WebSocket] = []
        for websocket in list(self._rooms.get((room_type, room_id), ())):
            try:
                await websocket.send_json(message)
            except Exception:  # noqa: BLE001 — any send failure means "gone"
                dead.append(websocket)
        for websocket in dead:
            self.leave(room_type, room_id, websocket)
            logger.debug("dropped dead socket from %s/%s", room_type, room_id)


# Module-level singleton, like the event bus (§3.1).
manager = ConnectionManager()
