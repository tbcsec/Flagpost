# ADR-0025: Multi-worker via a Redis broadcast relay behind the connection manager

**Status:** Accepted
**Date:** 2026-08-12
**Architecture reference:** `ARCHITECTURE.md` §4.1 (revises the single-process assumption of ADR-0005)

## Context

The [500-user load test](../load-testing/2026-08-12-500user-multicomp.md) showed
the single uvicorn worker is the capacity ceiling: at 500 concurrent users it
shed ~45 % of requests as connection resets while the DB pool (42/60) and CPU
(85 % of one core) had headroom — the signature of one event loop saturating
while the box's other cores sit idle. The fix that reclaims those cores is
running N worker processes. The owner's goal is "low thousands on one box"
(#189), explicitly *not* multi-machine horizontal scaling, which would add
operational weight that cuts against the `docker compose up` simplicity that is
a product selling point.

The blocker to multi-worker is that each worker process holds its own WebSocket
connections in memory. A broadcast raised on worker 1 (a solve, a scoreboard
delta, an announcement) reaches only worker 1's clients; the clients on workers
2..N get nothing. The real options were: (a) shard the WS layer so a room's
clients all land on one worker (sticky, fragile, defeats load balancing); (b)
relay *events* across workers so every worker re-runs each handler (double-fires
background side-effects like webhooks, and every worker recomputes scoreboards);
or (c) relay the *broadcast frames* across workers, handlers running once on the
emitting worker.

A second question was the shape of the seam. The rate limiter's `get_rate_limiter`
DI pattern is the house precedent, but it doesn't fit here: the ~15 broadcast
call sites are event-bus listeners (`from realtime import manager`), not FastAPI
request handlers, so they can't take a `Depends`.

## Decision

**Relay broadcast frames, not events, over a single Redis pub/sub channel, behind
the existing `manager` singleton.**

- `broadcast()` splits into local delivery + publish. Every worker's subscriber
  delivers received frames to *its* local sockets, skipping frames it published
  itself (a per-worker id tags each frame) so the emitting worker delivers once.
- The seam is `manager.attach_relay(relay)` at startup — not a `Depends` — so all
  ~15 call sites keep calling `manager.broadcast()` unchanged.
- **`exclude` never crosses the wire.** The excluded socket (the CRDT sender) is
  always on the emitting worker, which applies it during local delivery and skips
  its own relayed copy; other workers can't hold that socket, so the relayed
  payload carries only `{origin, room_type, room_id, message}`.
- **Single-worker attaches no relay** and stays a pure in-process fan-out with no
  Redis round-trip — byte-for-byte the ADR-0005 behaviour. `web_concurrency` (the
  conventional `WEB_CONCURRENCY` env var) selects the mode: `> 1` attaches the
  relay and **requires** `redis_url`; a startup guard refuses to boot otherwise,
  so a misconfigured multi-worker deploy fails loudly instead of silently
  dropping broadcasts to (N-1)/N of clients.

This revises — does not discard — ADR-0005: the event bus stays in-process and
per-worker (handlers run once on the emitting worker; audit writes hit the shared
DB; background webhooks/email fire once). Only the WS fan-out becomes cross-worker.

## Consequences

- **Positive:** one insertion point fixes scoreboard, activity, announcements,
  tickets, notifications, and collaborative editing, because all already funnel
  through `manager.broadcast()`. Single-worker/dev/test/zero-infra are unchanged
  (no Redis needed; the test transport skips the lifespan, so no relay attaches).
  Redis is already in the production compose (rate limiter), so multi-worker adds
  no new infrastructure component — the `docker compose up` story holds.
- **Negative / cost:** multi-worker makes Redis a hard dependency (guarded).
  Presence is still per-worker after this change and needs its own cross-worker
  rework ([ADR forthcoming / #189 Phase 2]) before multi-worker is *correct* —
  so `web_concurrency` stays 1 by default until that lands and a multi-worker load
  test validates it. The activity coalescer and scoreboard cache remain per-worker
  (efficiency-only: each worker batches/caches its own slice) — documented, not
  fixed here.
- **Forecloses:** nothing permanently. This is also the substrate for true
  horizontal (multi-machine) scaling later — the statelessness it forces is the
  same; only the Redis/DB endpoints would move off-box. Sharding the pub/sub
  channel by competition is a future optimisation if one channel saturates.
