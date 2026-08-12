# Load test — #207 onboarding fix + the default-flip decision (2026-08-13)

- **Builds on:** [multi-worker validation](2026-08-12-multiworker-validation.md)
  (which found multi-worker fixes steady state but the argon2 login storm
  oversubscribed cores) and #207 (argon2 `parallelism=1` + bounded hashing
  executors).
- **Scenario:** 1,500 users · 3 competitions (750/450/300) · same profile.
- **Raw:** [post-#207 single](2026-08-12-post207-single-1500-result.json) ·
  [post-#207 2-worker](2026-08-12-post207-2worker-1500-result.json) ·
  [8-vCPU 6-worker](2026-08-13-post207-8vcpu-6worker-1500-result.json)

## Verdict

**#207 fixed onboarding and ships. The core-aware default flip is _held_, and
this run explains why with a mechanism, not a hand-wave.** Multi-worker only
wins when the event loop is the bottleneck — one core pinned while others sit
idle (the 200–500-user regime #189 was built for). At 1,500 fully-onboarded
users the box is CPU-saturated on _every_ worker count, and there multi-worker
is neutral-to-slightly-harmful (coordination + a split DB pool with no extra
usable CPU). Flipping a default that ships to every operator is only justified
when headroom is the common case, and the evidence doesn't support that
universally — so multi-worker stays **opt-in**, for the regime where it wins.

## What #207 fixed (clean, reproducible)

The [previous run](2026-08-12-multiworker-validation.md) found N workers each ran
argon2 (p=4) on `asyncio.to_thread`'s ~min(32,cpu+4)-thread default pool,
oversubscribing cores during the login storm. #207 (p=1 — OWASP's server config,
m/t unchanged — plus a bounded login executor and a separate bulk-import pool)
fixes onboarding across the board:

| Metric | pre-#207 single | post-#207 single | pre-#207 4-worker | post-#207 4-worker |
|---|--:|--:|--:|--:|
| Users onboarded (of 1500) | 1017 | **1416** | 532 | 952 |
| Login p50 | 3919 ms | **424 ms** | 16447 ms | 14681 ms |

Single-worker onboarding went from 1,017 to **1,416** and login p50 from 3.9 s
to **424 ms** — a large, safe win independent of the flip (it helps every
deployment). Existing p=4 hashes still verify (argon2 reads params from the
stored hash).

## Why the flip is held — the mechanism

Two data points settle it, both at 1,500 users:

- **On 4 vCPU, 2 workers (the core-aware default for a 4-core box) was _worse_
  than 1 worker**: submit 502s 63 %→**83 %**, refetch 64 %→**78 %**. With every
  core already pinned (CPU 410 % of 400 %), a second worker adds context-switch
  and coordination cost and halves each worker's DB-pool slice, buying no extra
  compute.
- **On 8 vCPU, 6 workers pinned all 8 cores** (816 % of 800 %) and the run
  dissolved into harness-side queueing — httpx `PoolTimeout`s, and access tokens
  expiring _in the client queue_ (7,000+ spurious 401s), with 900-second
  "latencies" that are queue time, not service time. 1,500 closed-loop users
  simply offer more than 8 cores can take.

The through-line: **multi-worker converts idle cores into serving capacity; it
cannot create cores.** #189's win was real precisely because single-worker
pinned _one_ core and left three idle at 500 users. At 1,500 users nothing is
idle, so worker count stops mattering (or hurts).

## The measurement honesty note

This harness is **closed-loop**: each simulated client issues its next request as
soon as the last returns, so a faster backend is offered _more_ load until it
re-saturates. That's the right tool for "does it collapse, and where" (it found
the single-worker ceiling at 500). It's the _wrong_ tool for "is multi-worker's
steady state better at a load where both are near capacity" — the offered load
moves with backend speed, so the configs can't be held to equal load. A clean
flip validation needs an **open-loop (fixed-arrival-rate) harness** or real
production telemetry. Until then, changing the shipped default rests on evidence
this instrument can't provide.

## Decision & guidance

- **Ship #207** — the onboarding fix, valuable for every deployment.
- **Keep multi-worker opt-in** (`WEB_CONCURRENCY>1`, Phases 0–3). Enable it when
  the **event loop is your bottleneck**: a busy event with real core headroom on
  the box (CPU well under its limit while one core saturates). That's the regime
  where it turns idle cores into 0 %-502 steady state.
- **Do not flip the core-aware default.** It helps only with headroom and is
  neutral-to-harmful under saturation; a universal default needs stronger,
  open-loop evidence. Tracked on #189/#207.

_The four-vCPU cap matched the historical 200/500-user baselines for
comparability; the 8-vCPU run used a temporary, uncommitted overlay._
