"""Cross-worker presence membership (#189 Phase 2, ADR-0026).

Presence — "who's viewing this challenge / ticket" (§4.1) — is per-process state
in the connection manager, so across multiple uvicorn workers each sees only its
own members and the "who's here" list fragments. This is the shared layer that
makes the membership global.

Model (hybrid, so the common case keeps today's behaviour exactly):

- The manager still tracks *local* sockets and runs the local grace-debounce, so
  a same-worker tab reconnect suppresses flicker with no Redis round-trip — the
  overwhelmingly common case.
- This store holds the *global* membership in Redis:
    - ``pres:m:{rt}:{rid}``    HASH  user_id → member payload (JSON)
    - ``pres:live:{rt}:{rid}`` ZSET  "{user_id}|{worker_id}" → expiry timestamp
  A user is present iff **any** worker holds a non-expired liveness entry for
  them. Workers refresh their entries on a heartbeat while they hold a socket;
  a crashed worker's entries simply expire, so presence self-heals on worker
  death with no cross-worker eviction bookkeeping.
- ``members()`` prunes expired liveness and orphaned payloads on read (lazy
  self-heal), and every join/leave recomputes + broadcasts the global list
  through the Phase 1 relay — so no separate presence-change channel is needed.

Worker-death staleness is eventual: a dead worker's members vanish from the
computed list within the TTL and are re-broadcast on the next presence event in
that room (or shown correctly to the next joiner via the snapshot). Acceptable
for a low-stakes "who's here" display; a periodic reconcile is a later option.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

logger = logging.getLogger("realtime.presence")

# user_id and worker_id are UUID strings / hex — neither contains "|".
_SEP = "|"


def _mkey(room_type: str, room_id: str) -> str:
    return f"pres:m:{room_type}:{room_id}"


def _lkey(room_type: str, room_id: str) -> str:
    return f"pres:live:{room_type}:{room_id}"


class PresenceStore(Protocol):
    """Global presence membership seam. Swappable so tests can share one
    in-process store across several managers without a Redis server."""

    async def add(
        self, room_type: str, room_id: str, user_id: str, member: dict[str, Any]
    ) -> None: ...

    async def refresh_many(
        self, entries: list[tuple[str, str, str]]
    ) -> None: ...

    async def remove(self, room_type: str, room_id: str, user_id: str) -> None: ...

    async def members(self, room_type: str, room_id: str) -> list[dict[str, Any]]:
        ...

    async def close(self) -> None: ...


class RedisPresenceStore:
    """Redis implementation of :class:`PresenceStore`.

    ``now`` is injectable so tests are deterministic; production passes the real
    clock. TTL/heartbeat come from config: ``ttl`` must exceed
    ``heartbeat + grace`` so a live-but-idle member never expires between
    refreshes.
    """

    def __init__(
        self,
        redis_url: str,
        worker_id: str,
        *,
        ttl_seconds: float,
        max_connections: int = 50,
        acquire_timeout_seconds: float = 10.0,
        clock=None,
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
        self._worker_id = worker_id
        self._ttl = ttl_seconds
        if clock is None:
            import time

            clock = time.time
        self._now = clock
        # Whole-key GC: an empty room's keys expire if nothing refreshes them.
        # Generous vs the liveness TTL so active rooms (refreshed each heartbeat)
        # never lose the hash out from under live members.
        self._key_ttl = int(ttl_seconds * 4)

    def _tag(self, user_id: str) -> str:
        return f"{user_id}{_SEP}{self._worker_id}"

    async def add(
        self, room_type: str, room_id: str, user_id: str, member: dict[str, Any]
    ) -> None:
        now = self._now()
        mkey, lkey = _mkey(room_type, room_id), _lkey(room_type, room_id)
        pipe = self._redis.pipeline()
        pipe.hset(mkey, user_id, json.dumps(member))
        pipe.zadd(lkey, {self._tag(user_id): now + self._ttl})
        pipe.expire(mkey, self._key_ttl)
        pipe.expire(lkey, self._key_ttl)
        await pipe.execute()

    async def refresh_many(self, entries: list[tuple[str, str, str]]) -> None:
        if not entries:
            return
        now = self._now()
        pipe = self._redis.pipeline()
        touched: set[tuple[str, str]] = set()
        for room_type, room_id, user_id in entries:
            lkey = _lkey(room_type, room_id)
            pipe.zadd(lkey, {self._tag(user_id): now + self._ttl})
            touched.add((room_type, room_id))
        for room_type, room_id in touched:
            pipe.expire(_mkey(room_type, room_id), self._key_ttl)
            pipe.expire(_lkey(room_type, room_id), self._key_ttl)
        await pipe.execute()

    async def remove(self, room_type: str, room_id: str, user_id: str) -> None:
        now = self._now()
        mkey, lkey = _mkey(room_type, room_id), _lkey(room_type, room_id)
        # Drop this worker's liveness for the user, prune anything expired, then
        # decide if the user survives on some other worker.
        pipe = self._redis.pipeline()
        pipe.zrem(lkey, self._tag(user_id))
        pipe.zremrangebyscore(lkey, 0, now)
        pipe.zrange(lkey, 0, -1)
        _, _, survivors = await pipe.execute()
        still_present = any(
            tag.split(_SEP, 1)[0] == user_id for tag in survivors
        )
        if not still_present:
            await self._redis.hdel(mkey, user_id)

    async def members(self, room_type: str, room_id: str) -> list[dict[str, Any]]:
        now = self._now()
        mkey, lkey = _mkey(room_type, room_id), _lkey(room_type, room_id)
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(lkey, 0, now)  # prune expired liveness
        pipe.zrange(lkey, 0, -1)
        pipe.hgetall(mkey)
        _, live_tags, payloads = await pipe.execute()
        live_uids = {tag.split(_SEP, 1)[0] for tag in live_tags}

        out: list[dict[str, Any]] = []
        orphans: list[str] = []
        for uid, raw in payloads.items():
            if uid not in live_uids:
                orphans.append(uid)  # payload for a user no worker keeps alive
                continue
            try:
                out.append(json.loads(raw))
            except (ValueError, TypeError):
                orphans.append(uid)
        if orphans:
            await self._redis.hdel(mkey, *orphans)  # lazy self-heal
        out.sort(key=lambda m: m.get("name", ""))
        return out

    async def close(self) -> None:
        try:
            await self._redis.aclose()
        except Exception:  # noqa: BLE001 — best-effort teardown
            pass
