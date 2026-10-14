"""Cross-worker broadcast relay (#189).

The connection manager (``realtime.manager``) can only reach WebSocket objects
living in its *own* process. Once the backend runs as multiple uvicorn workers
(ADR-0005 superseded by ADR-0025), a broadcast raised on worker 1 — a solve, a
scoreboard delta, an announcement — must also reach the clients connected to
workers 2..N. This is that fan-out channel: workers publish broadcasts to a
single Redis pub/sub channel, and every worker's subscriber delivers each
received broadcast to its *local* sockets.

Deliberately dumb: it carries the manager's already-computed *results*, never
events. The manager still runs each event's handlers once, on the worker that
emitted the mutation, and relays two kinds of payload:

- a **broadcast** — ``{origin, room_type, room_id, message}`` (no ``kind``):
  every worker delivers the frame to its local sockets in that room;
- an **eviction** — ``{origin, kind: "evict", user_ids, room_type,
  room_id_prefix, code}``: every worker revokes and closes its local sockets
  for those users (GHSA-p679 — before this, revocation reached only the worker
  that handled the revoking request).

That keeps background side-effects (webhooks, email) firing exactly once and
avoids every worker recomputing a scoreboard. Because evictions now ride it,
the subscriber is supervised: a dropped Redis connection is resubscribed with
backoff, and the manager is told about the gap (see ``RedisRelay._supervise``).

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
GapHandler = Callable[[], Awaitable[None]]

# Resubscribe backoff after the pub/sub stream drops (GHSA-p679): quick first
# retry for a blip, capped so a long Redis outage doesn't spin.
_RESUBSCRIBE_INITIAL_S = 0.5
# Capped low: a subscribe attempt is cheap, and every second spent waiting
# after Redis is back is a second this worker misses peers' evictions.
_RESUBSCRIBE_MAX_S = 5.0
# How long a re-established stream must hold before the backoff resets.
_RESUBSCRIBE_STABLE_S = 30.0

# Liveness of the subscriber connection (GHSA-p679). A half-open TCP stream —
# a NAT / load-balancer / conntrack idle timeout that drops a quiet flow with no
# FIN or RST — never errors a blocking read, so a plain ``listen()`` waited on
# it forever: the worker went deaf with no gap reported. Instead poll, and
# after this much silence send a PING; no PONG within the timeout means the
# connection is dead, which the supervisor then treats as a drop.
_POLL_S = 1.0
_IDLE_PING_S = 15.0
_PING_TIMEOUT_S = 5.0


class RealtimeRelay(Protocol):
    """The seam the manager talks to. Swappable so tests can wire several
    in-process managers to one fake bus without a Redis server."""

    async def publish(self, payload: dict[str, Any]) -> None: ...

    async def start(
        self, handler: RelayHandler, *, on_gap: GapHandler | None = None
    ) -> None:
        """Begin delivering received payloads to ``handler`` (one per worker).
        ``on_gap`` is awaited after the subscription is re-established
        following a drop, since anything published in between was lost."""
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
        from redis.asyncio.retry import Retry
        from redis.backoff import NoBackoff

        pool = BlockingConnectionPool.from_url(
            redis_url,
            max_connections=max_connections,
            timeout=acquire_timeout_seconds,
            encoding="utf-8",
            decode_responses=True,
            # Pinned, not left to redis-py's defaults (GHSA-p679): with retries,
            # PubSub reconnects and resubscribes *silently* — the supervisor
            # never sees the drop, and whatever was published during it is lost
            # with no gap reported. A failed publish is retried by the manager.
            retry=Retry(NoBackoff(), 0),
            # Kernel-level backstop for a dead peer; the idle PING in
            # ``_listen`` is the primary detector.
            socket_keepalive=True,
        )
        self._redis = Redis(connection_pool=pool)
        self._pubsub: Any = None
        self._task: asyncio.Task | None = None

    async def publish(self, payload: dict[str, Any]) -> None:
        await self._redis.publish(_CHANNEL, json.dumps(payload))

    async def start(
        self, handler: RelayHandler, *, on_gap: GapHandler | None = None
    ) -> None:
        await self._subscribe()
        self._task = asyncio.ensure_future(self._supervise(handler, on_gap))

    async def _subscribe(self) -> None:
        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(_CHANNEL)

    async def _supervise(
        self, handler: RelayHandler, on_gap: GapHandler | None
    ) -> None:
        """Keep the subscription alive for the life of the worker (GHSA-p679).

        This used to be a single pass: on a dropped Redis connection the loop
        logged and returned, nothing restarted it, and the worker silently
        stopped hearing its peers for good — publishes still "succeeded". That
        was a liveness bug while the relay carried only broadcasts; once it
        carries evictions it is a security one, because a Redis restart would
        reopen cross-worker revocation on every worker with no error anywhere.

        So: on a drop, resubscribe with capped backoff. Pub/sub is at-most-once,
        so whatever was published during the gap is gone — once resubscribed,
        ``on_gap`` lets the manager compensate (it closes every local socket so
        clients re-handshake against current state)."""
        loop = asyncio.get_running_loop()
        delay = _RESUBSCRIBE_INITIAL_S
        while True:
            started = loop.time()
            await self._listen(handler)  # returns only when the stream drops
            # Reset the backoff only if the stream actually held. A subscribe
            # that succeeds against a flapping server and drops at once would
            # otherwise cycle every half-second — and fire on_gap, which closes
            # every socket on this worker, just as often.
            if loop.time() - started >= _RESUBSCRIBE_STABLE_S:
                delay = _RESUBSCRIBE_INITIAL_S
            while True:
                await asyncio.sleep(delay)
                try:
                    await self._close_pubsub()
                    await self._subscribe()
                    break
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 — Redis still down; keep trying
                    delay = min(delay * 2, _RESUBSCRIBE_MAX_S)
                    logger.warning(
                        "relay: resubscribe failed; retrying in %.1fs", delay
                    )
            # Grow the delay for the next drop too; the stable-stream check
            # above is what brings it back down.
            delay = min(delay * 2, _RESUBSCRIBE_MAX_S)
            logger.warning("relay: resubscribed after a dropped connection")
            if on_gap is not None:
                try:
                    await on_gap()
                except Exception:  # noqa: BLE001 — compensation failing mustn't kill the loop
                    logger.exception("relay: gap handler failed")

    async def _listen(self, handler: RelayHandler) -> None:
        """Deliver messages until the stream drops — including a *silent* drop,
        detected by the idle PING (see ``_IDLE_PING_S``). Returns on a drop."""
        loop = asyncio.get_running_loop()
        last_seen = loop.time()
        ping_sent_at: float | None = None
        try:
            while True:
                msg = await self._pubsub.get_message(timeout=_POLL_S)
                now = loop.time()
                if msg is None:
                    if ping_sent_at is not None:
                        if now - ping_sent_at >= _PING_TIMEOUT_S:
                            raise ConnectionError(
                                "relay: no PONG from Redis — connection is dead"
                            )
                    elif now - last_seen >= _IDLE_PING_S:
                        await self._pubsub.ping()
                        ping_sent_at = now
                    continue
                # Any traffic — a message, a PONG, a subscribe ack — proves
                # the connection is alive.
                last_seen = now
                ping_sent_at = None
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
            logger.exception("relay: subscriber stream dropped; resubscribing")

    async def _close_pubsub(self) -> None:
        if self._pubsub is None:
            return
        try:
            await self._pubsub.aclose()
        except Exception:  # noqa: BLE001 — the old connection is already broken
            pass
        self._pubsub = None

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
