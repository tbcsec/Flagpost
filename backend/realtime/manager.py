"""In-process WebSocket connection manager (ARCHITECTURE.md §4.1).

Rooms are keyed ``(room_type, room_id)`` — e.g. ``("scoreboard", <competition
id>)`` — mirroring the ``wss://…/ws/<type>/<id>`` URL shape. The manager only
tracks membership and fans out JSON frames; *who may join a room* is decided by
the room's registered authorizer (see ``realtime.router``), never here.

Multi-worker aware (#189, ADR-0025): each worker owns its real WebSocket
objects, so ``broadcast`` always delivers to *local* sockets, and — when a
:class:`realtime.relay.RealtimeRelay` is attached at startup (workers > 1) —
also publishes the frame so every other worker delivers it to *its* locals. A
single-worker deployment attaches no relay and stays a pure in-process fan-out
with no Redis round-trip, exactly as the original single-process design
(ADR-0005).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import WebSocket

from config import settings

if TYPE_CHECKING:
    from realtime.presence_store import PresenceStore
    from realtime.relay import RealtimeRelay

logger = logging.getLogger("realtime")

# Cap on concurrent sends within a single broadcast (#177). High enough that a
# few-hundred-socket room fans out in one wave, bounded so a huge room can't
# open an unbounded burst of send tasks at once.
_BROADCAST_CONCURRENCY = 64


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
        # Cross-worker fan-out (#189). None ⇒ single-worker: broadcast is a
        # pure local fan-out. A per-process id tags outgoing relayed frames so
        # this worker skips its own copy (it already delivered locally).
        self._relay: RealtimeRelay | None = None
        self._worker_id = uuid4().hex
        # Cross-worker presence (#189 Phase 2). None ⇒ single-worker: presence
        # lives entirely in ``_presence`` below, exactly as before. When a store
        # is attached, ``_presence`` stays the *local* view (socket tracking +
        # grace debounce + heartbeat source) and the store holds the *global*
        # membership that gets computed and broadcast.
        self._presence_store: PresenceStore | None = None
        self._heartbeat_task: asyncio.Task | None = None

    @property
    def worker_id(self) -> str:
        """This process's stable id — tags relayed frames and presence liveness
        so a worker can tell its own writes from its peers'."""
        return self._worker_id

    def attach_relay(self, relay: RealtimeRelay) -> None:
        """Wire a cross-worker relay (multi-worker mode). Call once at startup,
        before :meth:`start_relay`."""
        self._relay = relay

    async def start_relay(self) -> None:
        """Begin consuming relayed broadcasts from other workers. No-op when no
        relay is attached (single-worker)."""
        if self._relay is not None:
            await self._relay.start(self._on_relayed)

    async def stop_relay(self) -> None:
        """Tear down the relay subscriber. Safe no-op when none is attached."""
        if self._relay is not None:
            await self._relay.stop()

    def attach_presence_store(self, store: PresenceStore) -> None:
        """Wire a cross-worker presence store (multi-worker). Call once at
        startup, before :meth:`start_presence`."""
        self._presence_store = store

    async def start_presence(self, heartbeat_seconds: float) -> None:
        """Start the presence heartbeat that keeps this worker's members alive in
        the shared store. No-op when no store is attached (single-worker)."""
        if self._presence_store is not None and self._heartbeat_task is None:
            self._heartbeat_task = asyncio.ensure_future(
                self._presence_heartbeat(heartbeat_seconds)
            )

    async def stop_presence(self) -> None:
        """Stop the heartbeat and close the store. Safe no-op single-worker."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        if self._presence_store is not None:
            await self._presence_store.close()

    async def _presence_heartbeat(self, interval: float) -> None:
        """Refresh the shared-store liveness of every (room, user) this worker
        still holds a socket for, so a live-but-idle member never expires. A
        crashed worker simply stops refreshing and its members age out."""
        store = self._presence_store
        assert store is not None
        while True:
            try:
                await asyncio.sleep(interval)
                entries = [
                    (rt, rid, uid)
                    for (rt, rid), members in list(self._presence.items())
                    for uid in list(members.keys())
                ]
                await store.refresh_many(entries)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — a dropped Redis conn mustn't kill the loop
                logger.exception("presence heartbeat failed")

    async def _on_relayed(self, payload: dict[str, Any]) -> None:
        """Deliver a broadcast published by another worker to our local sockets.

        Skips frames this worker itself published — it already delivered those
        locally, so re-delivering the relayed copy would double-send."""
        if payload.get("origin") == self._worker_id:
            return
        await self._deliver_local(
            payload["room_type"], payload["room_id"], payload["message"]
        )

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
        """Send ``message`` as JSON to every socket in the room, across workers.

        Delivers to this worker's local sockets, then — when a relay is attached
        (multi-worker) — publishes the frame so every other worker delivers it
        to its own locals (#189). ``exclude`` skips one socket, used by the CRDT
        relay (§4.2) so a client doesn't receive an echo of its own update; it's
        always a socket on *this* worker, so it's applied to local delivery only
        and never crosses the relay (the excluded socket can't exist elsewhere).
        """
        await self._deliver_local(room_type, room_id, message, exclude=exclude)
        if self._relay is not None:
            await self._relay.publish(
                {
                    "origin": self._worker_id,
                    "room_type": room_type,
                    "room_id": room_id,
                    "message": message,
                }
            )

    async def _deliver_local(
        self,
        room_type: str,
        room_id: str,
        message: dict[str, Any],
        *,
        exclude: WebSocket | None = None,
    ) -> None:
        """Fan ``message`` out to this worker's sockets in the room.

        A socket that fails to send (client vanished mid-broadcast) is dropped
        from the room rather than failing the broadcast for its neighbours.
        Sends run concurrently (bounded by ``_BROADCAST_CONCURRENCY``), each
        under ``ws_send_timeout_seconds`` (#177): the old sequential loop let a
        single slow client — a full TCP send buffer on a congested link — stall
        delivery to the whole room. A socket that times out is treated as gone,
        like one that errors.
        """
        targets = [
            ws
            for ws in list(self._rooms.get((room_type, room_id), ()))
            if ws is not exclude
        ]
        if not targets:
            return

        semaphore = asyncio.Semaphore(_BROADCAST_CONCURRENCY)
        dead: list[WebSocket] = []

        async def _send(websocket: WebSocket) -> None:
            async with semaphore:
                try:
                    await asyncio.wait_for(
                        websocket.send_json(message),
                        timeout=settings.ws_send_timeout_seconds,
                    )
                except Exception:  # noqa: BLE001 — timeout (TimeoutError) or send failure = gone
                    dead.append(websocket)

        await asyncio.gather(*(_send(ws) for ws in targets))

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

    async def _publish_presence(self, room_type: str, room_id: str) -> None:
        """Broadcast the room's presence set. Multi-worker uses the shared
        store's *global* membership (computed once here, then relayed verbatim to
        every worker's clients); single-worker uses the local set. Either way
        the frame goes out through ``broadcast`` — so the Phase 1 relay carries
        it cross-worker without a separate presence channel."""
        if self._presence_store is not None:
            members = await self._presence_store.members(room_type, room_id)
        else:
            members = self.presence_members(room_type, room_id)
        await self.broadcast(
            room_type, room_id, {"type": "presence", "members": members}
        )

    async def presence_join(
        self, room_type: str, room_id: str, websocket: WebSocket, member: dict[str, Any]
    ) -> None:
        """Add ``websocket`` to the room's presence set under ``member['id']``.

        Cancels any pending debounced removal for that user (a reconnect inside
        the grace window), records the socket in the local view, publishes the
        member to the shared store when multi-worker, then broadcasts the
        refreshed set to the room.
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
        if self._presence_store is not None:
            await self._presence_store.add(room_type, room_id, user_id, member)
        await self._publish_presence(room_type, room_id)

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
        # Drop this worker's shared-store liveness; the store keeps the user
        # present only if another worker still holds them.
        if self._presence_store is not None:
            await self._presence_store.remove(room_type, room_id, user_id)
        await self._publish_presence(room_type, room_id)


# Module-level singleton, like the event bus (§3.1).
manager = ConnectionManager()
