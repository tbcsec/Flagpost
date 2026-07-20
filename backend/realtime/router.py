"""The WebSocket endpoint: ``/ws/{room_type}/{room_id}`` (ARCHITECTURE.md §4.1).

One endpoint serves every room type. The lifecycle, per §4.1 / ADR-0003:

1. Accept the connection.
2. **First-frame auth**: the client's first message must be
   ``{"token": "<access JWT>"}`` within ``ws_auth_timeout_seconds`` — the token
   is *never* a URL query parameter (it would leak into proxy logs / history).
   The same access token as REST is verified the same way.
3. **Room authorization**: each room type registers an authorizer (below) that
   decides whether this user may join this room — permission checks stay
   server-side and per-resource, exactly like REST routes (§7.6).
4. On success the server confirms with ``{"type": "auth_ok"}``, sends the
   room's snapshot frame if the room type provides one (so a client that
   reconnects after missing broadcasts is immediately current), and joins the
   socket to the room. Inbound frames after auth are ignored — Tier 1 rooms are
   broadcast-only; presence (§4.1) is Tier 2.

Close codes mirror HTTP: 4401 auth failed/timeout, 4403 not allowed, 4404
unknown room type. Room types are registered by the modules that own them
(e.g. the scoring module registers "scoreboard"), keeping this endpoint free
of feature knowledge.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from auth.security import decode_access_token
from config import settings
from db import SessionLocal
from models.user import User
from realtime.manager import manager

logger = logging.getLogger("realtime")

router = APIRouter()

# May this user join this room?
Authorizer = Callable[[AsyncSession, User, str], Awaitable[bool]]
# Optional initial frame sent right after auth_ok (e.g. the current scoreboard).
SnapshotProvider = Callable[[AsyncSession, User, str], Awaitable[dict[str, Any] | None]]


@dataclass(frozen=True)
class RoomType:
    authorize: Authorizer
    snapshot: SnapshotProvider | None = None


_room_types: dict[str, RoomType] = {}


def register_room_type(
    room_type: str,
    *,
    authorize: Authorizer,
    snapshot: SnapshotProvider | None = None,
) -> None:
    """Register a room type. Called by the module that owns the resource."""
    _room_types[room_type] = RoomType(authorize=authorize, snapshot=snapshot)


@router.websocket("/ws/{room_type}/{room_id}")
async def room_socket(websocket: WebSocket, room_type: str, room_id: str) -> None:
    await websocket.accept()

    room = _room_types.get(room_type)
    if room is None:
        await websocket.close(code=4404, reason="Unknown room type")
        return

    # First-frame auth, bounded by a short server timeout (§4.1).
    try:
        first = await asyncio.wait_for(
            websocket.receive_json(), timeout=settings.ws_auth_timeout_seconds
        )
    except (TimeoutError, asyncio.TimeoutError):
        await websocket.close(code=4401, reason="Auth timeout")
        return
    except (WebSocketDisconnect, ValueError):
        # Client hung up, or sent a non-JSON first frame.
        return

    token = first.get("token") if isinstance(first, dict) else None
    if not token:
        await websocket.close(code=4401, reason="Missing auth token")
        return
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    async with SessionLocal() as db:
        user = await db.get(User, payload.get("sub"))
        if user is None:
            await websocket.close(code=4401, reason="User no longer exists")
            return
        if not await room.authorize(db, user, room_id):
            await websocket.close(code=4403, reason="Not allowed in this room")
            return
        await websocket.send_json(
            {"type": "auth_ok", "room_type": room_type, "room_id": room_id}
        )
        if room.snapshot is not None:
            snapshot = await room.snapshot(db, user, room_id)
            if snapshot is not None:
                await websocket.send_json(snapshot)

    manager.join(room_type, room_id, websocket)
    try:
        # Broadcast-only rooms: drain (and ignore) client frames until it hangs
        # up, so the socket stays responsive to pings/closes.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.leave(room_type, room_id, websocket)
