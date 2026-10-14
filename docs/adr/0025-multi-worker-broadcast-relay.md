# ADR-0025: Multi-worker via a Redis broadcast relay behind the connection manager

**Status:** Accepted (amended 2026-10-14 — the relay also carries evictions, and
its subscriber is supervised; see the Amendment)
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
  payload carries only `{origin, room_type, room_id, message}`. *(Since the
  2026-10-14 amendment it also carries a second, eviction payload kind.)*
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

## Amendment: evictions ride the relay, and the subscriber is supervised (2026-10-14)

**Context.** The decision above relayed *broadcast frames* and nothing else.
Server-driven WebSocket revocation (#10) — closing a user's sockets on a ban,
deletion, team removal, or role unassignment/edit, since room authorization runs
only at the handshake — was never part of it. Eviction handlers run once, on the
emitting worker (the event bus is per-process, per the decision above), and the
manager could only close that worker's sockets. In a multi-worker or
multi-instance deployment a revoked user therefore kept every socket held on any
other worker indefinitely. Tracked as **GHSA-p679-w29c-326x**, fixed in #462 and
shipped in v1.7.1. Single-worker deployments were never affected.

**Decision.** The relay carries a second payload kind, and its subscriber becomes
a security dependency that must stay live:

- **Eviction payload** — `{origin, kind: "evict", user_ids, room_type,
  room_id_prefix, code}`. A broadcast is a payload with no `kind`, so mixed-version
  workers during a rolling deploy stay safe in both directions (an old worker
  fails that one relay delivery and logs it; a new worker still understands old
  broadcasts). This is still "relay results, not events": the eviction *handler*
  still runs once, on the emitting worker; only its outcome — which users' sockets
  to revoke — crosses the wire.
- **Revoke before anything is awaited.** `ConnectionManager.evict_users` marks the
  matching local sockets revoked synchronously, then publishes and closes
  concurrently, each close bounded. A revoked socket receives nothing more and the
  router refuses its inbound frames, so neither a stalled close nor the event bus
  cutting the handler off at its timeout can leave access in place. Peers do the
  same on receipt, closing in the background so one stalled socket can't block
  the single subscriber task.
- **The router serves only sockets the manager vouches for** — tracked *and* not
  revoked. A socket dropped from the indexes by a failed broadcast send is closed,
  not just forgotten, since eviction can no longer find it.
- **A handshake re-checks a per-user revocation epoch** right after joining, so a
  revocation landing while the socket is not yet indexed isn't missed.
- **The subscriber is supervised.** It resubscribes with capped backoff after a
  dropped connection — including a *silently* dead one, detected by an idle PING
  that gets no PONG — and the pool pins `Retry(NoBackoff(), 0)` so redis-py can't
  reconnect behind the supervisor's back. Because pub/sub is at-most-once, a
  failed eviction publish is retried in the background, and after any gap the
  worker conservatively closes all its sockets (staggered) so clients
  re-handshake against current state.

**Consequences.**

- **Positive:** revocation holds across workers, and the failure modes of the
  channel it now depends on (Redis restart, a NAT dropping an idle subscriber
  connection, pool exhaustion on publish) degrade to "reconnect and
  re-authorize" rather than "silently keep access".
- **Negative / cost:** a Redis restart now makes every client of every worker
  reconnect (spread over a few seconds), and a slow client whose broadcast send
  times out is disconnected and reconnects instead of lingering stale. The relay
  is no longer *purely* best-effort fan-out — a silently deaf subscriber is now a
  security bug, not just a liveness one, which is why it is supervised.
- **Unchanged / still open:** sockets are still never re-validated after the
  handshake except through these events. Expiring a socket with its access token
  (a backstop that would also cover password change, logout-all and API-token
  revocation, which don't evict today) needs the frontend to refresh before
  reconnecting, and is deliberately not part of this amendment. Relayed
  *broadcasts* are still delivered inline in the subscriber task.
