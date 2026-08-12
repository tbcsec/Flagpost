# Load testing

Flagpost is meant to run live events, so we load-test it against the **real
production stack** and publish the results — methodology, harness, and numbers —
in this directory. If a release claims a capacity, there is a reproducible run
behind it.

> These are point-in-time snapshots against a specific commit and a specific
> machine. They exist to find *architectural* limits (what serializes, what
> saturates), not to certify an SLA. Re-run them on your own hardware before
> trusting a number for your deployment.

## What's here

| File | What it is |
|---|---|
| `sim.py` | The simulator — drives N browser-like clients across M competitions, optionally sharded over several worker processes so the load generator itself never becomes the bottleneck. |
| `loadtest.override.yml` | A compose overlay: publishes the backend port for the harness and caps the backend at a realistic event-VPS size. |
| `<date>-baseline.md` | A written report for a run (verdict, results, bottlenecks, caveats). |
| `<date>-*-result.json` | The raw metrics that report was written from. |

## What the simulator actually does

Each simulated user behaves like a browser, not a bare HTTP client:

- a real `POST /api/auth/login`, then joins the competition;
- holds the **four shell WebSockets** a real client holds — `scoreboard`,
  `activity`, `announcements`, and its per-user `user` room — open for the whole
  run, plus transient `challenge` presence sockets while "viewing" a challenge;
- reproduces the frontend's **exact refetch behaviour**: an activity-room ping
  is mapped to query keys and a per-key 2.5 s throttle (mirroring
  `frontend/src/lib/live.ts`), and only the keys the client's current page
  actually mounts trigger a REST GET — so the "one solve → N refetches"
  amplification is faithful, not guessed;
- submits flags at a competitive cadence within the per-subject rate limit.

It runs these phases: **doors open** (login + socket storm), **steady play**,
**announcement blast** (one per competition), a **hot-competition burst** (one
competition submit-spams while the others play normally — the tenancy-isolation
probe), **reconnect herd** (drop and re-establish every socket), and a
**slow-client probe** (congested readers during a solve burst). It samples
backend CPU/memory (`docker stats`), the Postgres connection count
(`pg_stat_activity`), and — when sharded — the harness's own CPU, so a report can
state whether the tails are the server's or the load generator's. Writes a JSON +
printed summary, with per-competition and steady-vs-burst windowed breakdowns.

### Multiple competitions and sharding

A single asyncio loop saturates client-side well below ~500 browser-like
clients, which would poison the numbers with harness queueing. So the run can be
split across worker processes: the parent bootstraps the instance and an absolute
epoch-aligned phase schedule, spawns `SHARDS` workers (each owning `idx % SHARDS`,
a stride that puts users from every competition in every shard), and merges their
raw metrics into one report. Users are assigned to competitions deterministically
(same assignment in every shard) via `COMP_SPLIT`.

## Running it

Prerequisites: Docker + Compose, and a Python with `httpx` and `websockets`
(the backend venv already has both — `cd backend && python -m venv .venv &&
.venv/bin/pip install -r requirements-dev.txt`).

```bash
# 1. Bring up the production stack with the load-test overlay, on a FRESH DB.
#    (down -v first if you have a prior stack — the sim runs the first-run
#    setup wizard, which only fires on an unconfigured instance.)
docker compose -f docker-compose.yml -f docs/load-testing/loadtest.override.yml \
  up -d --build

# 2. Run the simulator (from the repo root, using the backend venv).
backend/.venv/bin/python docs/load-testing/sim.py            # 200 users, 1 comp
SMOKE=1 backend/.venv/bin/python docs/load-testing/sim.py    # 10-user self-test

# 500 users across 3 competitions (250/150/100), 4 sharded workers:
USERS=500 COMPS=3 COMP_SPLIT=250,150,100 SHARDS=4 \
  backend/.venv/bin/python docs/load-testing/sim.py

# 3. Tear the stack down when done.
docker compose -f docker-compose.yml -f docs/load-testing/loadtest.override.yml \
  down -v
```

Knobs are environment variables (`USERS`, `COMPS`, `COMP_SPLIT`, `SHARDS`,
`IMPORT_BATCH`, `SMOKE`) plus constants at the top of `sim.py` (challenge count,
phase durations, submission cadence). It targets the Caddy front door (`:8080`)
when reachable and falls back to the direct backend port (`:8001`, published by
the overlay).

## Honest limits of this harness

- **Single host, loopback.** It exercises server-side mechanics (serialization,
  pool saturation, fan-out), not real multi-machine network loss or per-client
  bandwidth. Absolute latencies inflate once the harness's own connection pool
  backs up — read them as "the system entered congestion," and lean on the
  server-side signals (DB pool depth, CPU headroom, per-endpoint status codes).
- **One IP.** Per-IP-limited paths see a single client; where that flatters the
  result, the report says so.
- **Isolated DB.** The overlay caps the backend but leaves Postgres unconstrained
  — a true all-in-one VPS shares cores with the database, so it would be a little
  worse than these numbers.

## Reports

- [`2026-08-10-baseline.md`](2026-08-10-baseline.md) — first baseline at 200
  users; motivated the v1.4.0 load-hardening work (#87, #174–#178). Includes the
  post-fix and #188 stage-2 re-runs.
- [`2026-08-12-500user-multicomp.md`](2026-08-12-500user-multicomp.md) — 500
  users across 3 competitions. Found the single-process ceiling (a 45 % 502 storm
  with DB-pool and CPU headroom to spare) — the concrete evidence for #189
  (multi-worker), plus that concurrent competitions share one performance fate.
- [`2026-08-12-multiworker-validation.md`](2026-08-12-multiworker-validation.md)
  — 1,500-user A/B, single- vs 4-worker. Multi-worker eliminates the steady-state
  502 storm (30–45 % → 0 %), but the argon2 login storm oversubscribes cores
  under multiple workers — so the default flip is held pending that fix.
