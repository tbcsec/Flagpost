# ADR-0026: Cross-worker presence via heartbeat-TTL liveness in Redis

**Status:** Accepted
**Date:** 2026-08-12
**Architecture reference:** `ARCHITECTURE.md` §4.1 (extends ADR-0025)

## Context

ADR-0025 made WebSocket *broadcasts* cross-worker, but presence — the "who's
viewing this challenge / ticket" set (§4.1) — was still per-process state in the
connection manager. Across N uvicorn workers each sees only its own members, so
the "who's here" list fragments: a user on worker 1 and a user on worker 2 in
the same room never see each other. This is the last correctness gap before
multi-worker can be enabled (#189 Phase 2).

Presence has three properties that make it harder than broadcast fan-out: it is
**deduped per user** across tabs *and now across workers*; it clears on a
**grace debounce** so a brief reconnect doesn't flicker the list; and a
**crashed worker** must not leave ghost members forever. The real options were:
(a) a pure Redis-TTL rewrite that discards the current in-memory model; (b)
sticky routing so a room's members all land on one worker (fragile, defeats load
balancing); or (c) a hybrid that keeps the existing local model and layers a
shared liveness view for the cross-worker cases.

## Decision

**Hybrid: keep the per-worker local model; add a Redis liveness layer for global
membership.**

- The manager still tracks *local* sockets and runs the *local* grace-debounce,
  so a same-worker tab reconnect (the overwhelmingly common case) suppresses
  flicker with no Redis round-trip and behaves exactly as before.
- Redis holds the *global* membership:
  - `pres:m:{rt}:{rid}` HASH — `user_id → member payload`
  - `pres:live:{rt}:{rid}` ZSET — `"{user_id}|{worker_id}" → expiry timestamp`
  A user is present iff **any** worker holds a non-expired liveness entry. Each
  worker refreshes its entries on a heartbeat (`ttl` must exceed
  `heartbeat + grace`, e.g. 30 > 10 + 5) while it holds a socket; a crashed
  worker simply stops refreshing and its members age out — no cross-worker
  eviction bookkeeping.
- `members()` prunes expired liveness and orphaned payloads on read (lazy
  self-heal). Every join/leave recomputes the global list and broadcasts it
  through the ADR-0025 relay, so **no separate presence-change channel is
  needed** — the frame is computed once on the acting worker and relayed
  verbatim to every worker's clients.

## Consequences

- **Positive:** membership is the correct global union; same-worker flicker
  suppression is unchanged; worker death self-heals within the TTL with no
  distributed eviction logic. Single-worker attaches no store and is byte-for-
  byte the previous behaviour (all existing presence tests pass untouched); the
  test transport skips the lifespan so no store is attached in tests.
- **Negative / cost:** worker-death staleness is *eventual* — a crashed worker's
  members vanish from the computed list within the TTL and are re-broadcast on
  the next presence event in the room (or shown correctly to the next joiner via
  the snapshot), not instantly. Acceptable for a low-stakes "who's here"
  display; a periodic reconcile that pushes the pruned list proactively is a
  later option if needed. Multi-worker also makes Redis mandatory (guarded at
  startup, ADR-0025).
- **Forecloses:** nothing. The same liveness model extends to multi-machine
  horizontal scale unchanged (the worker id is already globally unique). If a
  single Redis ever bottlenecks, the keys shard by room like the relay channel.
