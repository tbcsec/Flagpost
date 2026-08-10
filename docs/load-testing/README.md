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
| `sim.py` | The simulator — one asyncio process driving N browser-like clients. |
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

It runs five phases: **doors open** (login + socket storm), **steady play**,
**announcement blast**, **reconnect herd** (drop and re-establish every socket),
and a **slow-client probe** (congested readers during a solve burst). It samples
backend CPU/memory (`docker stats`) and the Postgres connection count
(`pg_stat_activity`) throughout, and writes a JSON + printed summary.

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
backend/.venv/bin/python docs/load-testing/sim.py            # full 200-user run
SMOKE=1 backend/.venv/bin/python docs/load-testing/sim.py    # 10-user self-test

# 3. Tear the stack down when done.
docker compose -f docker-compose.yml -f docs/load-testing/loadtest.override.yml \
  down -v
```

Knobs (user count, challenge count, phase durations, submission cadence) are
constants at the top of `sim.py`. It targets the Caddy front door
(`:8080`) when reachable and falls back to the direct backend port
(`:8001`, published by the overlay).

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
  users; motivated the v1.4.0 load-hardening work (#87, #174–#178).
