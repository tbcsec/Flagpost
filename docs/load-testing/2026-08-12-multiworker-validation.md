# Load test — multi-worker validation A/B at 1,500 users (2026-08-12)

- **Commit:** `1aa82d4` (v1.4.0-src, #189 Phases 0–3 merged)
- **Scenario:** 1,500 concurrent users · 3 competitions (750/450/300) · 30
  challenges each · 6 harness shards · same ~13-min phase profile as the
  [500-user run](2026-08-12-500user-multicomp.md)
- **Stack:** production `docker compose` capped at **4 vCPU / 4 GB** backend
  (the same modest event-VPS cap as before), Postgres/Redis/MinIO unconstrained
- **A/B:** identical scenario, **single-worker** (`WEB_CONCURRENCY=1`) vs
  **4-worker** (`WEB_CONCURRENCY=4`, relay + presence + scheduler sidecar)
- **Raw:** [single](2026-08-12-singleworker-1500-result.json) ·
  [multi](2026-08-12-multiworker-1500-result.json)

## Verdict

**Multi-worker decisively fixes the steady-state ceiling it was built for — and
the run surfaced a second, CPU-bound bottleneck that means the production default
is _not_ being flipped yet.** In steady play the 502 storm disappears entirely
(submit 30 %→**0 %**, refetch 45 %→**0 %**; latencies collapse from seconds to
milliseconds), confirming #189's core hypothesis: the single event loop was the
gameplay ceiling. But **doors-open got _worse_**: four worker processes each run
their own argon2 threadpool, oversubscribing the 4 capped cores during the login
storm, so onboarding dropped from 1,017 to 532 users and login p50 rose from
3.9 s to 16.4 s. The steady win and the onboarding regression are two different
bottlenecks, and the second one gates the default flip.

## The A/B

| Metric | Single-worker | 4-worker | |
|---|--:|--:|---|
| **Submit 502 rate** | 30 % | **0 %** | ✅ event-loop ceiling gone |
| **Refetch 502 rate** | 45 % | **0 %** | ✅ |
| Submit p50 / p95 | 1856 / 6951 ms | **14 / 28 ms** | ✅ |
| Refetch p50 | 408 ms | **16 ms** | ✅ |
| HTTP 500 (submit+refetch) | 296 | **0** | ✅ |
| **Login p50 / p95** | 3919 / 21717 ms | **16447 / 27985 ms** | ❌ worse |
| **Users onboarded** (login 200) | **1017** | 532 | ❌ worse |
| Steady load offered (attempts) | 9765 | 1878 | ⚠️ confound (see below) |
| Postgres connections peak | 62 / 60 (pinned) | **150 / 200** (budget split) | ✅ |
| Backend CPU peak | 415 % | 408 % | both peg during login storm |
| Harness CPU peak (6 shards) | 119 % | 130 % (of ~540) | ✅ tails are real |

## Reading it honestly

**The steady-state win is real and large, and it's what #189 was about.** Once
users are in and playing, four event loops serve submits and refetches with
**zero connection resets** and millisecond latency, where one event loop shed
30–45 % as 502s. The Postgres budget split worked exactly as designed — 4 workers
peaked at 150 connections against the bumped 200 cap, versus single-worker
pinning its 60. Tenancy isolation also held far better under multi-worker (quiet
comps' submit p95 stayed ~30 ms through the hot-comp burst, vs seconds
single-worker), because the shared event loop is no longer the contended
resource.

**But the A/B is confounded by onboarding, and I won't pretend otherwise.**
Multi-worker onboarded roughly half as many users (532 vs 1017), so it carried
far less steady load (1,878 vs 9,765 attempts). Part of the pristine steady
numbers is simply "fewer users got in to generate load." The *per-request
quality* win (0 % vs 45 % 502, ms vs seconds) is not explained away by that — it
holds regardless — but a clean equal-load steady A/B would need the onboarding
bottleneck removed first.

**Why onboarding regressed — the second bottleneck.** Doors-open is an argon2
login storm: 1,500 password verifies, and argon2 is deliberately CPU-slow. With
one process, hashing runs in a single threadpool that keeps the 4 cores busy
efficiently. With four worker processes, each has its **own** CPU-bound
threadpool (sized from the host/quota core count, not divided by worker count),
so up to ~4× as many hashing threads contend for the same 4 cores — thrashing,
not parallelism. The total work is fixed by the core count; more processes just
oversubscribe it. That's why login p50 quadrupled and a third of users timed out
before onboarding. This is **not** the event-loop-dispatch ceiling multi-worker
fixes — it's a distinct CPU/argon2 constraint that multi-worker, on a
CPU-capped box, makes worse.

## Decision: ship multi-worker as opt-in, hold the default flip

- **Multi-worker stays available and correct** (Phases 0–3 merged): opt in with
  `WEB_CONCURRENCY>1`. For a steady, already-onboarded low-thousands event it is
  a large improvement.
- **The production default stays 1 worker.** Flipping it core-aware now would
  regress onboarding on CPU-constrained boxes — the exact common deployment. The
  flip is **gated on fixing the argon2 login-storm oversubscription**: bound each
  worker's CPU-bound (hashing) executor so the total across workers ≈ cores (a
  shared semaphore or a per-worker pool sized `cores // workers`), so doors-open
  doesn't thrash. Filed as the flip's blocker.
- After that fix, re-run this same A/B — the expectation is multi-worker wins on
  *both* axes (steady state already does; onboarding should match or beat
  single-worker once hashing isn't oversubscribed), at which point the default
  flip is justified.

## Honest limits

- Single host, loopback, one client IP; Postgres/Redis unconstrained (a true
  all-in-one VPS shares cores with the DB — the argon2 contention would be
  *worse*, reinforcing the hold decision). The 4-vCPU cap is backend-only.
- Closed-loop; the harness's own CPU (max 130 % of ~540 possible across 6
  shards) confirms the tails are server-side, not load-generator queueing.
- The two runs are not equal-load (see the confound above); the steady-state
  quality comparison is per-request and sound, the throughput comparison is not.
