# Load test — 500-user, 3-competition (2026-08-12)

- **Commit:** `3663082` (v1.4.0-src, carrying #174–#188 + #187 pool bump)
- **Scenario:** 500 concurrent users split across **3 simultaneous competitions**
  (250 / 150 / 100) · 30 challenges each · ~2000 held-open WebSockets · ~13 min
- **Stack:** production `docker compose` (Caddy → **single** uvicorn worker →
  Postgres/Redis/MinIO), fresh DB
- **Backend limit:** 4 vCPU / 4 GB (a realistic mid-size event VPS)
- **Harness:** [`sim.py`](sim.py), now multi-competition and **sharded across 4
  worker processes** · raw metrics:
  [`2026-08-12-500user-multicomp-result.json`](2026-08-12-500user-multicomp-result.json)

This extends the [200-user baseline](2026-08-10-baseline.md) two ways: **2.5×
the users**, and **spread across three tenants** to test whether the
per-competition scoping that holds at the data layer also isolates *performance*
under a noisy neighbour.

> **Why this run is trustworthy where the 200-user tails weren't.** The harness
> now shards across 4 processes and reports its own CPU: it peaked at **65 %** of
> one core-equivalent per the ps sampler (well under the ~360 % that would mean
> client-side queueing). So unlike the single-process 200-user runs — where
> every tail carried a "might be the harness" caveat — **the failures below are
> the server's, not the load generator's.**

## Verdict

**500 users on a single worker is past the ceiling — and this run finally shows
*why*, unambiguously.** The platform sheds **~45 % of steady-state requests as
502s** (42 % of submits, 49 % of refetches) while the **database pool (42/60)
and average CPU (p50 85 %) both have headroom**. That combination — mass
connection *resets*, not timeouts, with spare pool and spare cores — is the
definitive signature of the **single-process / single-event-loop** limit
(ADR-0005), and it is exactly the evidence [#189](https://github.com/tbcsec/Flagpost/issues/189)
(multi-worker) was gated on. At 200 users the platform held; at 500 it does not,
and no amount of pool or RAM moves that ceiling.

**Data isolation across competitions held; performance isolation did not.**
Solves were counted correctly per competition and no cross-tenant leakage
appeared, but a submit storm in the largest competition roughly **doubled the
p95 of the two quiet ones** — because all three share one event loop.

## Failure points, in the order they were reached

### 1. Bootstrap — a 500-row user import exceeds a 30 s client/proxy timeout (T‑0)
The very first operation failed before a single competitor arrived. Argon2 is
deliberately ~**64 ms/row**, so a single `POST /api/users/import` of 500 rows
runs ~32 s — past a 30 s client (and typical proxy) timeout. The request
**succeeded server-side anyway** (501 users created), so the operator sees an
error for an operation that actually completed, and a naive retry produces
confusing skip/conflict output. Chunked to 100 rows/batch it is a clean **6.4 s
each**.
- **Mitigation.** Lower the *synchronous* import ceiling (`MAX_IMPORT_ROWS` is
  1000) to what fits comfortably under a proxy timeout (~150–200), or move large
  imports to a background job returning `202 Accepted` + progress. Document the
  batch size regardless. Cheap, high-value, ships independently.

### 2. Doors-open — ~half of users fail to fully onboard (T+0 … 120 s)
Only **239 / 500** users completed login + join + their 4 shell sockets. Login
p95 hit **454 ms** (p99 1086 ms), there were **5 352 WebSocket connect
failures**, and backend CPU peaked at **354 %** — the argon2 threadpool under a
500-way login storm colliding with the connection-accept load of ~2000 opening
sockets on one worker.
- **Mitigation.** Partly the same single-worker ceiling as #3. Independently:
  stagger/queue the WS handshake (the `ws_handshake_rate_limit` exists but
  admits bursts), and consider argon2 cost/threadpool tuning so the login storm
  doesn't starve the accept loop. The real fix is horizontal (#3's mitigation).

### 3. Steady + burst — the 502 storm (T+120 … 517 s) — *the main event*
Caddy logged **31 612 × 502**, every one a `read: connection reset by peer` from
the backend at a consistent **~280 ms** — the single worker **resetting**
connections it can't service, not timing out. This is not the database pool
(peaked 42 of 60) and not aggregate compute (CPU p50 85 %, and the harness proves
the tails are real). The one event loop is saturated **serialising WebSocket
fan-out** — 844 596 activity frames + 158 542 scoreboard frames delivered — and
HTTP request dispatch loses the race.
- **Mitigation — this is [#189](https://github.com/tbcsec/Flagpost/issues/189).**
  Run **multiple uvicorn workers** behind Caddy. Crucially this is *not* just
  `--workers N`: broadcasts must move to a **Redis-backed pub/sub relay** or a
  solve on worker 1 only reaches the ~1/N clients connected to worker 1
  (scoreboard/activity silently break for everyone else). The rate limiter is
  already Redis-backed; the event-bus/WS-broadcast layer and presence are not.
  So #189 is "workers + shared fan-out + shared presence," and **this run is the
  evidence to prioritise it.**

### 4. Redis connection-pool exhaustion (concurrent with #3) — 150 × HTTP 500
A smaller, hard-error class traced to `redis.asyncio` —
`get_available_connection: IndexError: pop from empty list`. The Redis rate
limiter builds its client with `redis.asyncio.from_url(...)` and the **default,
uncapped connection pool**, which is not safe under this level of concurrent
churn.
- **Mitigation.** Give it a bounded `BlockingConnectionPool` with an explicit
  `max_connections` (the same "size the pool on purpose" move #187 made for
  Postgres). Small, safe, removes the 500s independent of #3.

### 5. Noisy-neighbour — no performance isolation across competitions
When the 250-user competition entered its submit burst, the two quiet
competitions degraded almost as much as the hot one:

| Competition | submit p95 steady → burst | refetch p95 steady → burst |
|---|--:|--:|
| comp0 (hot, 250u) | 393 → **903 ms** | 225 → 386 ms |
| comp1 (quiet, 150u) | 399 → **895 ms** | 193 → 314 ms |
| comp2 (quiet, 100u) | 385 → **823 ms** | 206 → 399 ms |

Medians barely moved (they even improved, as quiet-comp clients naturally issue
fewer requests during the window) — it's the **tail** that a noisy neighbour
inflates, and it inflates every tenant by roughly the same amount because they
share one event loop. **Data-plane isolation is intact** (per-competition solve
counts correct, queries scoped, no cross-tenant reads); **performance isolation
is a property the single process cannot provide.** #189's multi-worker model
does not partition tenants either — the honest takeaway is that *concurrent
competitions on one instance share a performance fate*, which matters for anyone
planning to host several events on one box.

## Results

| Phase | Metric | Result | |
|---|---|---|---|
| Bootstrap | 500-row import (single POST) | **>30 s timeout** (server completed) | ❌ |
| Bootstrap | import, chunked 100/batch | 6.4 s/batch | ✅ |
| Doors open | fully onboarded | **239 / 500** | ❌ |
| Doors open | login p50 / p95 / p99 | 82 / 454 / 1086 ms | ⚠️ |
| Doors open | WS connect failures | **5 352** | ❌ |
| Steady/burst | submit success | **58 %** (7042/12360; 42 % 502) | ❌ |
| Steady/burst | refetch success | **51 %** (21490/42576; 49 % 502) | ❌ |
| Steady/burst | Caddy 502 (backend reset) | **31 612**, ~280 ms each | ❌ |
| Steady/burst | HTTP 500 (Redis pool) | 150 | ❌ |
| Steady/burst | goodput (solves) | 1 633 (c0 914 / c1 425 / c2 294) | ⚠️ |
| Resource | Postgres connections | **42 / 60** (headroom) | ✅ |
| Resource | backend CPU p50 / max | 85 % / 354 % of 400 % | ⚠️ |
| Resource | harness CPU (4 shards) | max **65 %** — tails are real | ✅ |
| Isolation | quiet-comp p95 under burst | **~2× worse** (shared loop) | ⚠️ |

## The one chart that explains it

The pool has headroom and average CPU is under one core, yet half of all requests
are reset at the door — the signature of a single-process concurrency wall, not a
resource shortage:

```
Requests served OK   ████████████▌            ~55%
Requests reset (502) ███████████▌             ~45%   <- backend resets, ~280ms
DB pool utilisation  ████████▍                42/60  (headroom)
Backend CPU (median) █████████████▋           85% of one core-equiv (bursty)
Harness CPU          ██████▌                  65% — NOT the bottleneck
```

## What would move the ceiling (ordered)

1. **Ship #189 — multi-worker + Redis-backed WS fan-out + shared presence.** The
   only change that raises the concurrency ceiling. This run is the trigger
   evidence; scope it as more than `--workers`.
2. **Interim single-worker hardening (buys margin, doesn't move the wall):**
   bounded Redis pool (#4), import chunking/async (#1), uvicorn
   `--limit-concurrency` + listen-backlog + FD-limit tuning, WS-handshake
   staggering (#2). These cut the *hard-error* rate and make degradation
   graceful, but the 502 ceiling stays ~one-worker.
3. **Vertical scaling is the wrong lever here.** More cores help the argon2 login
   storm, but the steady-state 502s occur at 85 % of *one* core with the others
   idle — the bottleneck is single-event-loop dispatch, which extra cores can't
   touch. This confirms the earlier analysis: past ~200–300 concurrent,
   horizontal beats vertical.

## Honest limits

- Single host, loopback, one client IP, Postgres/Redis unconstrained (a true
  all-in-one VPS would share cores with the DB — so real all-in-one numbers would
  be *worse*). The 4-vCPU cap is on the backend only.
- Closed-loop: a 502 returns fast, so the harness immediately offers the next
  request — the 45 % error rate reflects offered load exceeding single-worker
  capacity, not a fixed user population all failing.
- The `~280 ms` reset point is consistent but its precise mechanism (uvicorn
  backpressure vs. kernel accept-queue overflow vs. FD pressure) wasn't
  instrumented to the syscall; the *class* of failure (single worker resets
  under connection-concurrency load) is certain from the Caddy logs + worker
  count + resource headroom.

_Raw metrics: [`2026-08-12-500user-multicomp-result.json`](2026-08-12-500user-multicomp-result.json)._
