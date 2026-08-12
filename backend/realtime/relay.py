"""Cross-worker broadcast relay (#189).

The connection manager (``realtime.manager``) can only reach WebSocket objects
living in its *own* process. Once the backend runs as multiple uvicorn workers
(ADR-0005 superseded by ADR-0025), a broadcast raised on worker 1 — a solve, a
scoreboard delta, an announcement — must also reach the clients connected to
workers 2..N. This is that fan-out channel: workers publish broadcasts to a
single Redis pub/sub channel, and every worker's subscriber delivers each
received broadcast to its *local* sockets.

Deliberately dumb: it carries the already-serialized broadcast payload
(``{origin, room_type, room_id, message}``), not events. The manager still runs
each event's handlers once, on the worker that emitted the mutation; only the
resulting frames are relayed. That keeps background side-effects (webhooks,
email) firing exactly once and avoids every worker recomputing a scoreboard.

The ``exclude`` socket (the CRDT sender) never crosses the wire: it always lives
on the originating worker, which excludes it during its own local delivery and
skips its own relayed copy (the ``origin`` check in the manager). So a relayed
payload needs no socket identity — just the room and the frame.

Single-worker deployments attach no relay at all: ``broadcast`` stays a pure
in-process fan-out with no Redis round-trip, exactly as before.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

logger = logging.getLogger("realtime.relay")

# One channel for all rooms: the payload carries (room_type, room_id), and the
# per-worker fan-out volume is modest (one publish per broadcast, not per
# socket). Sharding the channel by competition is a later optimisation if a
# single channel ever becomes the bottleneck.
_CHANNEL = "flagpost:realtime:broadcast"

RelayHandler = Callable[[dict[str, Any]], Awaitable[None]]


class RealtimeRelay(Protocol):
    """The seam the manager talks to. Swappable so tests can wire several
    in-process managers to one fake bus without a Redis server."""

    async def publish(self, payload: dict[str, Any]) -> None: ...

    async def start(self, handler: RelayHandler) -> None:
        """Begin delivering received payloads to ``handler`` (one per worker)."""
        ...

    async def stop(self) -> None: ...


class RedisRelay:
    """Redis pub/sub implementation of :class:`RealtimeRelay`.

    Uses a bounded ``BlockingConnectionPool`` for the same reason the rate
    limiter does (#189 Phase 0a) — the default pool races under churn. Publish
    and subscribe share the client; the subscriber runs as one background task
    reading the pub/sub stream and invoking the handler per message.
    """

    def __init__(
        self,
        redis_url: str,
        *,
        max_connections: int = 50,
        acquire_timeout_seconds: float = 10.0,
    ) -> None:
        from redis.asyncio import BlockingConnectionPool, Redis

        pool = BlockingConnectionPool.from_url(
            redis_url,
            max_connections=max_connections,
            timeout=acquire_timeout_seconds,
            encoding="utf-8",
            decode_responses=True,
        )
        self._redis = Redis(connection_pool=pool)
        self._pubsub: Any = None
        self._task: asyncio.Task | None = None

    async def publish(self, payload: dict[str, Any]) -> None:
        await self._redis.publish(_CHANNEL, json.dumps(payload))

    async def start(self, handler: RelayHandler) -> None:
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(_CHANNEL)
        self._task = asyncio.ensure_future(self._listen(handler))

    async def _listen(self, handler: RelayHandler) -> None:
        try:
            async for msg in self._pubsub.listen():
                if msg.get("type") != "message":
                    continue
                try:
                    payload = json.loads(msg["data"])
                except (ValueError, TypeError):
                    logger.warning("relay: dropped un-decodable payload")
                    continue
                try:
                    await handler(payload)
                except Exception:  # noqa: BLE001 — one bad frame mustn't kill the loop
                    logger.exception("relay: handler failed for a payload")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a dropped Redis conn shouldn't crash the worker
            logger.exception("relay: subscriber loop exited unexpectedly")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe(_CHANNEL)
                await self._pubsub.aclose()
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass
            self._pubsub = None
        try:
            await self._redis.aclose()
        except Exception:  # noqa: BLE001
            pass
