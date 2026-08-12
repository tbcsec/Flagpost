"""Flagpost live-event capacity simulation (multi-competition capable).

Drives the REAL production docker stack (Caddy -> single-process backend ->
Postgres/Redis/MinIO) with N simulated competitors split across M concurrent
competitions, each client behaving like a browser: 4 shell WebSockets
(scoreboard, activity, announcements, user) held open, plus transient
challenge-presence sockets while "viewing" a challenge, and — crucially — the
exact frontend refetch behaviour (lib/live.ts): an activity ping maps to query
keys, each on a 2.5s leading+trailing throttle, and only the keys mounted by
the client's current page trigger a real REST GET.

Phases:
  1. doors open        — login + join + connect storm
  2. steady play       — submits + navigation + presence churn (all comps)
  3. announcements     — one all-participants blast per competition (mid-steady)
  3b. hot-comp burst   — competition 0 submit-spams while the others keep
                         playing normally: the tenancy-isolation probe. Per-comp
                         windowed metrics let the report compare the quiet
                         comps' latency during the burst vs during steady.
  4. reconnect herd    — every socket dropped and re-established at once
  5. slow-client probe — congested readers + solve burst (rank 0 only)

Scaling honestly: one asyncio loop saturates client-side well below 500
simulated browsers, which would poison the numbers with harness queueing. So
the run can be SHARDED across worker processes: the parent bootstraps the
instance, writes a bootstrap file + an absolute epoch schedule, spawns SHARDS
workers (each owning the user indices idx % SHARDS == rank, a stride that
gives every shard users in every competition), samples docker/postgres/harness
resources, then merges the shards' raw metrics into one report. Phases align
across shards by sleeping to shared wall-clock epochs.

Run:  .venv/bin/python sim.py                                (200 users, 1 comp)
      USERS=500 COMPS=3 COMP_SPLIT=250,150,100 SHARDS=4 .venv/bin/python sim.py
      SMOKE=1 COMPS=2 SHARDS=2 .venv/bin/python sim.py       (harness self-test)
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import statistics  # noqa: F401  (kept for ad-hoc analysis in the REPL)
import sys
import time
from collections import Counter, defaultdict

import httpx
import websockets

SMOKE = os.environ.get("SMOKE") == "1"
RANK = int(os.environ.get("RANK", "-1"))  # -1 = single process or parent
SHARDS = int(os.environ.get("SHARDS", "1"))

# ---- knobs ------------------------------------------------------------------
N_USERS = int(os.environ.get("USERS", "10" if SMOKE else "200"))
N_COMPS = int(os.environ.get("COMPS", "1"))
N_CHALLENGES = 6 if SMOKE else 30          # per competition
N_DYNAMIC = 2 if SMOKE else 10             # of N_CHALLENGES, the rest static
USER_PW = "loadtest-passw0rd"

DOORS_OPEN_S = 15 if SMOKE else 120
STEADY_S = 40 if SMOKE else 300
ANNOUNCE_AT_S = 20 if SMOKE else 240       # offset into steady
BURST_S = 12 if SMOKE else 60              # hot-competition burst (phase 3b)
SLOW_PROBE_S = 20 if SMOKE else 80

SUBMIT_MIN_GAP, SUBMIT_MAX_GAP = (3.0, 9.0) if SMOKE else (6.0, 15.0)
BURST_MIN_GAP, BURST_MAX_GAP = (0.6, 1.8)  # comp-0 cadence during the burst
CORRECT_FRACTION = 0.25                    # of submissions that use a real flag
NAV_MIN_GAP, NAV_MAX_GAP = (8.0, 20.0)
PRESENCE_VIEW_MIN, PRESENCE_VIEW_MAX = (6.0, 14.0)
N_SLOW_CLIENTS = 3 if SMOKE else 8
# Rows per mass-import POST. Argon2 is ~100ms/row by design, so 500 in one
# request runs past any sane client/proxy timeout (this run's finding #1).
IMPORT_BATCH = int(os.environ.get("IMPORT_BATCH", "100"))

ADMIN = {"display_name": "loadadmin", "email": "loadadmin@example.com", "password": "loadadmin-passw0rd"}
COMP_NAMES = ["Load Test Alpha", "Load Test Bravo", "Load Test Charlie",
              "Load Test Delta", "Load Test Echo"]


def comp_split() -> list[int]:
    """Users per competition. COMP_SPLIT="250,150,100" or equal by default."""
    raw = os.environ.get("COMP_SPLIT")
    if raw:
        parts = [int(x) for x in raw.split(",")]
        if len(parts) != N_COMPS or sum(parts) != N_USERS:
            sys.exit(f"COMP_SPLIT must have {N_COMPS} parts summing to {N_USERS}")
        return parts
    base, rem = divmod(N_USERS, N_COMPS)
    return [base + (1 if i < rem else 0) for i in range(N_COMPS)]


def comp_of(idx: int, split: list[int]) -> int:
    """Deterministic user->competition assignment — identical in every shard."""
    upto = 0
    for ci, n in enumerate(split):
        upto += n
        if idx < upto:
            return ci
    return len(split) - 1


# ---- endpoints --------------------------------------------------------------
HTTP_CADDY, WS_CADDY = "http://localhost:8080", "ws://localhost:8080"
HTTP_DIRECT, WS_DIRECT = "http://localhost:8001", "ws://localhost:8001"
HTTP = WS = ""  # resolved in parent / read from bootstrap file in workers

# ---- metrics ----------------------------------------------------------------
rest_lat: dict[str, list[float]] = defaultdict(list)
rest_status: dict[str, Counter] = defaultdict(Counter)
submit_correct_lat: list[float] = []
ws_connect_lat: dict[str, list[float]] = defaultdict(list)
ws_frames: dict[str, int] = Counter()
ws_errs = Counter()
counters = Counter()
probe_lags: list[float] = []
resource_samples: list[dict] = []
timeline: list[str] = []
# (epoch, comp_idx, cls, ms, status) — flat so shards merge by concatenation
# and the report can slice by phase window for the isolation analysis.
comp_events: list[list] = []


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(round((p / 100) * (len(xs) - 1)))))
    return xs[k]


def note(msg: str) -> None:
    tag = f"[shard{RANK}] " if RANK >= 0 else ""
    stamp = f"[{time.strftime('%H:%M:%S')}] {tag}{msg}"
    print(stamp, flush=True)
    timeline.append(stamp)


async def sleep_until(epoch: float) -> None:
    delay = epoch - time.time()
    if delay > 0:
        await asyncio.sleep(delay)


# ---- activity -> query-key -> REST mapping (mirrors frontend/src/lib/live.ts)-
def _dash(cid):
    return [("dashboard", cid, "stats"), ("dashboard", cid, "recent-solves"),
            ("dashboard", cid, "challenge-health"), ("dashboard", cid, "me")]


def keys_for_activity(event: str, cid: str) -> list[tuple]:
    if event == "challenge.solved":
        # #188: a solve carries a {solve_count, value} delta that the client
        # patches into the cached challenge card in place — it no longer refetches
        # the whole ["challenges"] list. (In team mode a teammate would refetch;
        # this harness runs individual mode, so no client is a teammate.) The
        # dashboard/analytics/standings keys are still invalidated.
        return [*_dash(cid), ("analytics", cid), ("participants", cid)]
    if event == "challenge.attempted":
        return [("dashboard", cid, "stats"), ("dashboard", cid, "challenge-health"), ("analytics", cid)]
    if event == "competition.member_joined":
        return [("participants", cid), ("teams", cid), ("dashboard", cid, "stats"), ("analytics", cid)]
    return []


# query key -> (path, is_participant_reachable). Staff-only surfaces are never
# mounted by a competitor, so invalidateQueries wouldn't refetch them.
def key_to_path(key: tuple, cid: str) -> str | None:
    m = {
        ("challenges", cid): f"/api/competitions/{cid}/challenges",
        ("participants", cid): f"/api/competitions/{cid}/participants",
        ("dashboard", cid, "stats"): f"/api/competitions/{cid}/dashboard/stats",
        ("dashboard", cid, "recent-solves"): f"/api/competitions/{cid}/dashboard/recent-solves",
        ("dashboard", cid, "challenge-health"): f"/api/competitions/{cid}/dashboard/challenge-health",
        ("dashboard", cid, "me"): f"/api/competitions/{cid}/dashboard/me",
    }
    return m.get(key)


# what each "page" mounts (which of the invalidated keys actually refetch)
PAGE_MOUNTS = {
    "challenges": lambda cid: {("challenges", cid)},
    # A participant dashboard mounts only participant-reachable widgets:
    # stats/recent-solves/me are challenge_view; challenge-health is staff-only
    # (view_competition_analytics), so a competitor's browser never mounts it.
    "dashboard": lambda cid: {("dashboard", cid, "stats"),
                              ("dashboard", cid, "recent-solves"),
                              ("dashboard", cid, "me")},
    "scoreboard": lambda cid: set(),          # updates via its own WS room
    "participants": lambda cid: {("participants", cid)},
}


class Throttle:
    """Per-key leading+trailing 2.5s throttle (mirrors createThrottledInvalidator)."""

    def __init__(self, fire, ms: float = 2.5):
        self.fire = fire
        self.win = ms
        self.open: dict = {}
        self.pending: dict = {}

    def push(self, keys: list[tuple]):
        now = time.monotonic()
        for k in keys:
            if k in self.open and now < self.open[k]:
                self.pending[k] = True
            else:
                self.open[k] = now + self.win
                asyncio.create_task(self.fire(k))


# ---- HTTP helper ------------------------------------------------------------
async def req(client: httpx.AsyncClient, method: str, path: str, cls: str,
              token: str | None = None, comp: int | None = None,
              timeout: float = 30, **kw) -> httpx.Response | None:
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    t0 = time.monotonic()
    try:
        r = await client.request(method, HTTP + path, headers=headers, timeout=timeout, **kw)
    except Exception as e:  # noqa: BLE001
        rest_status[cls][type(e).__name__] += 1
        if comp is not None:
            comp_events.append([time.time(), comp, cls, None, type(e).__name__])
        return None
    ms = (time.monotonic() - t0) * 1000
    rest_lat[cls].append(ms)
    rest_status[cls][r.status_code] += 1
    if comp is not None:
        comp_events.append([time.time(), comp, cls, round(ms, 1), r.status_code])
    return r


# ---- bootstrap (admin, parent/rank-single only) ------------------------------
async def bootstrap(client: httpx.AsyncClient) -> tuple[list[dict], str]:
    # 1. Setup wizard (fresh instance) or fall back to admin login.
    r = await req(client, "POST", "/api/setup", "setup", json={
        "admin": ADMIN, "platform_name": "LoadTest", "default_palette": "slate",
        "accent": "#2b67c6", "registration_open": True, "update_checks_enabled": False,
    })
    if r is not None and r.status_code == 201:
        note("setup wizard: created owner")
        token = r.json()["access_token"]
    else:
        note(f"setup returned {getattr(r, 'status_code', 'ERR')} — logging in as existing admin")
        lr = await req(client, "POST", "/api/auth/login", "login",
                       json={"identifier": ADMIN["display_name"], "password": ADMIN["password"]})
        token = lr.json()["access_token"]

    # 2. Competitions (individual, public, always-on) with per-comp challenges.
    comps: list[dict] = []
    for ci in range(N_COMPS):
        name = f"{COMP_NAMES[ci % len(COMP_NAMES)]} {time.strftime('%Y')}"
        r = await req(client, "POST", "/api/competitions", "admin", token=token, json={
            "name": name, "participation_mode": "individual", "visibility": "public",
        })
        cid = r.json()["id"]
        challenges = []
        for i in range(N_CHALLENGES):
            dynamic = i < N_DYNAMIC
            flag = f"flag{{loadtest-c{ci}-{i:03d}}}"
            body = {"title": f"Challenge {i:03d}", "flag_type": "static", "flag": flag, "points": 500}
            if dynamic:
                body.update({"scoring_type": "dynamic", "min_points": 100, "decay": 50})
            r = await req(client, "POST", f"/api/competitions/{cid}/challenges", "admin", token=token, json=body)
            chid = r.json()["id"]
            await req(client, "POST", f"/api/competitions/{cid}/challenges/{chid}/publish", "admin", token=token)
            challenges.append({"id": chid, "flag": flag})
        comps.append({"cid": cid, "name": name, "challenges": challenges})
        note(f"competition {ci}: {cid} ({name}) with {len(challenges)} challenges")

    # 3. Import all accounts via the mass-import CSV (dogfoods #171). No roles —
    #    each self-joins its assigned competition in phase 1 (the real
    #    doors-open path).
    #
    #    Chunked at IMPORT_BATCH deliberately: argon2 is ~100ms/row by design,
    #    so a single 500-row POST runs well past a 30s client/proxy timeout —
    #    the first thing this run found (see the report). A real operator hits
    #    the same wall, so the harness does what they'd have to do, and records
    #    per-batch latency under "import" so the report can quantify it.
    created = 0
    for start in range(0, N_USERS, IMPORT_BATCH):
        chunk = range(start, min(start + IMPORT_BATCH, N_USERS))
        lines = ["display_name,password"] + [f"loadtest{n:04d},{USER_PW}" for n in chunk]
        csv = ("\n".join(lines) + "\n").encode()
        t0 = time.monotonic()
        r = await req(client, "POST", "/api/users/import", "import", token=token,
                      timeout=300, files={"file": ("roster.csv", csv, "text/csv")})
        if r is None or r.status_code != 200:
            note(f"user import batch @{start} FAILED ({getattr(r, 'status_code', 'timeout')})")
            continue
        rep = r.json()
        created += rep["created"]
        note(f"user import batch {start:4d}-{chunk[-1]:4d}: created={rep['created']} "
             f"skipped={rep['skipped']} errors={rep['errors']} in {(time.monotonic()-t0):.1f}s")
    note(f"user import total: created={created}/{N_USERS}")
    return comps, token


# ---- client -----------------------------------------------------------------
class Client:
    def __init__(self, idx: int, client: httpx.AsyncClient, comp_idx: int,
                 cid: str, challenges: list[dict]):
        self.idx = idx
        self.name = f"loadtest{idx:04d}"
        self.http = client
        self.comp_idx = comp_idx
        self.cid = cid
        self.challenges = challenges
        self.token: str | None = None
        self.uid: str | None = None
        self.page = random.choices(
            ["challenges", "dashboard", "scoreboard", "participants"],
            weights=[50, 30, 15, 5])[0]
        self.mounts = PAGE_MOUNTS[self.page](cid)
        self.sockets: dict[str, websockets.WebSocketClientProtocol] = {}
        self.readers: list[asyncio.Task] = []
        self.throttle = Throttle(self._refetch)
        self.solved: set[str] = set()
        self.alive = True
        self.slow = False

    async def login(self) -> bool:
        r = await req(self.http, "POST", "/api/auth/login", "login",
                      json={"identifier": self.name, "password": USER_PW})
        if r is None or r.status_code != 200:
            counters["login_fail"] += 1
            return False
        self.token = r.json()["access_token"]
        self.uid = r.json()["user"]["id"]
        return True

    async def join(self):
        await req(self.http, "POST", f"/api/competitions/{self.cid}/join", "join",
                  token=self.token, comp=self.comp_idx)

    async def initial_fetch(self):
        for key in self.mounts:
            p = key_to_path(key, self.cid)
            if p:
                await req(self.http, "GET", p, "refetch", token=self.token, comp=self.comp_idx)

    async def _refetch(self, key: tuple):
        if key in self.mounts:
            p = key_to_path(key, self.cid)
            if p:
                await req(self.http, "GET", p, "refetch", token=self.token, comp=self.comp_idx)

    async def connect_shell(self):
        rooms = [("scoreboard", self.cid), ("activity", self.cid),
                 ("announcements", self.cid), ("user", self.uid)]
        for rt, rid in rooms:
            await self._open(rt, rid)

    async def _open(self, rt: str, rid: str, mode: str | None = None):
        uri = f"{WS}/ws/{rt}/{rid}"
        t0 = time.monotonic()
        try:
            ws = await websockets.connect(uri, max_queue=8 if self.slow else 64,
                                          open_timeout=20, ping_interval=None)
            frame = {"token": self.token}
            if mode:
                frame["mode"] = mode
            await ws.send(json.dumps(frame))
            ack = await asyncio.wait_for(ws.recv(), timeout=20)
            if json.loads(ack).get("type") != "auth_ok":
                ws_errs["auth"] += 1
                await ws.close()
                return
        except Exception:  # noqa: BLE001
            ws_errs["connect"] += 1
            return
        ws_connect_lat[rt].append((time.monotonic() - t0) * 1000)
        self.sockets[f"{rt}:{rid}"] = ws
        self.readers.append(asyncio.create_task(self._read(rt, ws)))

    async def _read(self, rt: str, ws):
        try:
            async for raw in ws:
                if self.slow:
                    await asyncio.sleep(3.0)  # congested client: drain very slowly
                ws_frames[rt] += 1
                if rt == "activity":
                    try:
                        f = json.loads(raw)
                    except ValueError:
                        continue
                    if f.get("type") == "activity" and f.get("event"):
                        self.throttle.push(keys_for_activity(f["event"], self.cid))
        except Exception:  # noqa: BLE001
            ws_errs["read"] += 1

    async def submit_once(self):
        ch = random.choice(self.challenges)
        correct = random.random() < CORRECT_FRACTION and ch["id"] not in self.solved
        flag = ch["flag"] if correct else f"flag{{wrong-{random.randint(0, 1<<30)}}}"
        path = f"/api/competitions/{self.cid}/challenges/{ch['id']}/submit"
        t0 = time.monotonic()
        r = await req(self.http, "POST", path, "submit", token=self.token, comp=self.comp_idx,
                      json={"flag": flag})
        if r is None:
            return
        counters["attempts"] += 1
        counters[f"attempts_c{self.comp_idx}"] += 1
        if r.status_code == 429:
            counters["submit_429"] += 1
            return
        if r.status_code == 200 and r.json().get("correct"):
            dt = (time.monotonic() - t0) * 1000
            if not r.json().get("already_solved"):
                self.solved.add(ch["id"])
                counters["solves"] += 1
                counters[f"solves_c{self.comp_idx}"] += 1
                submit_correct_lat.append(dt)

    async def presence_view(self):
        ch = random.choice(self.challenges)
        key = f"challenge:{ch['id']}"
        if key in self.sockets:
            return
        await self._open("challenge", ch["id"], mode="view")
        await asyncio.sleep(random.uniform(PRESENCE_VIEW_MIN, PRESENCE_VIEW_MAX))
        ws = self.sockets.pop(key, None)
        if ws:
            await ws.close()

    async def steady(self, until_epoch: float, burst_until_epoch: float | None = None):
        """Normal play until ``until_epoch``; then, if this client's comp is the
        hot one (comp 0) and a burst window follows, submit-spam through it —
        every other comp keeps playing normally through the burst window, so
        the report can compare their latency against the steady window."""

        async def submit_loop():
            while self.alive and time.time() < until_epoch:
                await asyncio.sleep(random.uniform(SUBMIT_MIN_GAP, SUBMIT_MAX_GAP))
                await self.submit_once()
            if burst_until_epoch is None:
                return
            if self.comp_idx == 0:
                while self.alive and time.time() < burst_until_epoch:
                    await asyncio.sleep(random.uniform(BURST_MIN_GAP, BURST_MAX_GAP))
                    await self.submit_once()
            else:
                while self.alive and time.time() < burst_until_epoch:
                    await asyncio.sleep(random.uniform(SUBMIT_MIN_GAP, SUBMIT_MAX_GAP))
                    await self.submit_once()

        stop_epoch = burst_until_epoch or until_epoch

        async def nav_loop():
            while self.alive and time.time() < stop_epoch:
                await asyncio.sleep(random.uniform(NAV_MIN_GAP, NAV_MAX_GAP))
                self.page = random.choices(
                    ["challenges", "dashboard", "scoreboard", "participants"],
                    weights=[50, 30, 15, 5])[0]
                self.mounts = PAGE_MOUNTS[self.page](self.cid)
                await self.initial_fetch()

        async def presence_loop():
            while self.alive and time.time() < stop_epoch:
                await asyncio.sleep(random.uniform(PRESENCE_VIEW_MIN, PRESENCE_VIEW_MAX))
                await self.presence_view()

        await asyncio.gather(submit_loop(), nav_loop(), presence_loop())

    async def close_sockets(self):
        for t in self.readers:
            t.cancel()
        self.readers.clear()
        for ws in list(self.sockets.values()):
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        self.sockets.clear()


# ---- resource sampler (parent / single-process only) --------------------------
async def sample_resources(stop: asyncio.Event, harness_pids: list[int]):
    name_backend = "flagpost-backend-1"
    name_pg = "flagpost-postgres-1"
    while not stop.is_set():
        cpu = mem = pg = harness_cpu = None
        try:
            p = await asyncio.create_subprocess_exec(
                "docker", "stats", "--no-stream", "--format", "{{.CPUPerc}} {{.MemUsage}}",
                name_backend, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await p.communicate()
            parts = out.decode().split()
            if parts:
                cpu = parts[0]
                mem = parts[1] if len(parts) > 1 else None
        except Exception:  # noqa: BLE001
            pass
        try:
            p = await asyncio.create_subprocess_exec(
                "docker", "exec", name_pg, "psql", "-U", "flagpost", "-d", "flagpost",
                "-tAc", "select count(*) from pg_stat_activity where datname='flagpost'",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await p.communicate()
            pg = out.decode().strip()
        except Exception:  # noqa: BLE001
            pass
        if harness_pids:
            # Honest-limits telemetry: if the harness itself pins its cores, the
            # client-side tails are queueing artifacts, and the report must say so.
            try:
                p = await asyncio.create_subprocess_exec(
                    "ps", "-o", "%cpu=", "-p", ",".join(str(x) for x in harness_pids),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                out, _ = await p.communicate()
                vals = [float(v) for v in out.decode().split() if v]
                harness_cpu = round(sum(vals), 1)
            except Exception:  # noqa: BLE001
                pass
        resource_samples.append({"t": round(time.time() - T0, 1), "cpu": cpu, "mem": mem,
                                 "pg_conns": pg, "harness_cpu": harness_cpu})
        try:
            await asyncio.wait_for(stop.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pass


# ---- worker ------------------------------------------------------------------
T0 = 0.0


async def run_clients(comps: list[dict], admin_token: str, schedule: dict,
                      my_indices: list[int], split: list[int], is_rank0: bool):
    """The phase engine — runs in each shard (or inline for SHARDS=1)."""
    limits = httpx.Limits(max_connections=max(64, len(my_indices) * 2),
                          max_keepalive_connections=max(32, len(my_indices)))
    client = httpx.AsyncClient(limits=limits)

    clients = []
    for idx in my_indices:
        ci = comp_of(idx, split)
        clients.append(Client(idx, client, ci, comps[ci]["cid"], comps[ci]["challenges"]))

    # ---- Phase 1: doors open — spread onboarding across the window -----------
    doors_end = schedule["doors_end"]
    note(f"PHASE 1 — doors open: {len(clients)} users over {doors_end - time.time():.0f}s")

    async def onboard(c: Client, at: float):
        await sleep_until(at)
        if not await c.login():
            return
        await c.join()
        await c.connect_shell()
        await c.initial_fetch()

    now = time.time()
    await asyncio.gather(*(onboard(c, random.uniform(now, doors_end - 1)) for c in clients))
    live = [c for c in clients if c.token and c.sockets]
    note(f"doors-open done — {len(live)}/{len(clients)} onboarded, "
         f"{sum(len(c.sockets) for c in clients)} sockets open")

    # ---- Phase 2/3/3b: steady play + announcements + hot-comp burst ----------
    steady_end, burst_end = schedule["steady_end"], schedule["burst_end"]
    note(f"PHASE 2 — steady play until T+{steady_end - T0:.0f}s, "
         f"then PHASE 3b burst (comp 0 hot) until T+{burst_end - T0:.0f}s")

    async def announce_later():
        if not is_rank0:
            return
        await sleep_until(schedule["announce_at"])
        note("PHASE 3 — announcement blast, one per competition")
        for ci, comp in enumerate(comps):
            t0 = time.monotonic()
            r = await req(client, "POST", f"/api/competitions/{comp['cid']}/announcements",
                          "announce", token=admin_token, comp=ci,
                          json={"title": "Load test broadcast",
                                "body": "All-participants announcement under load.",
                                "severity": "info"})
            note(f"announcement comp{ci} -> {getattr(r, 'status_code', 'ERR')} "
                 f"in {(time.monotonic() - t0) * 1000:.0f}ms")
            await asyncio.sleep(5.0)

    await asyncio.gather(*(c.steady(steady_end, burst_end) for c in live), announce_later())
    note("steady + burst complete")

    # ---- Phase 4: reconnect herd ---------------------------------------------
    await sleep_until(schedule["reconnect_at"])
    note("PHASE 4 — reconnect herd: dropping all sockets, reconnecting simultaneously")
    for c in live:
        await c.close_sockets()
    await sleep_until(schedule["reconnect_at"] + 1.0)
    p4 = time.monotonic()

    async def reconnect(c: Client):
        await c.connect_shell()
        await c.initial_fetch()

    await asyncio.gather(*(reconnect(c) for c in live))
    note(f"reconnect herd done in {time.monotonic() - p4:.1f}s — "
         f"{sum(len(c.sockets) for c in live)} sockets re-established")

    # ---- Phase 5: slow-client head-of-line probe (rank 0, comp 0) -------------
    if is_rank0:
        note(f"PHASE 5 — slow-client probe: {N_SLOW_CLIENTS} congested readers + solve burst")
        c0 = [c for c in live if c.comp_idx == 0]
        slow = c0[:N_SLOW_CLIENTS]
        fast = c0[N_SLOW_CLIENTS:2 * N_SLOW_CLIENTS + 20]
        cid0 = comps[0]["cid"]
        for c in slow:
            c.slow = True
            old = c.sockets.pop(f"scoreboard:{cid0}", None)
            if old:
                await old.close()
            await c._open("scoreboard", cid0)

        end = time.time() + SLOW_PROBE_S
        while time.time() < end:
            solver = random.choice(fast) if fast else (c0[-1] if c0 else live[-1])
            unsolved = [ch for ch in solver.challenges if ch["id"] not in solver.solved]
            if not unsolved:
                break
            ch = random.choice(unsolved)
            t0 = time.monotonic()
            r = await req(client, "POST",
                          f"/api/competitions/{solver.cid}/challenges/{ch['id']}/submit",
                          "submit", token=solver.token, comp=solver.comp_idx,
                          json={"flag": ch["flag"]})
            if r is not None and r.status_code == 200 and r.json().get("correct"):
                solver.solved.add(ch["id"])
                probe_lags.append((time.monotonic() - t0) * 1000)
            await asyncio.sleep(2.0)
        note(f"slow-client probe complete ({len(probe_lags)} probe solves)")
    else:
        # Other shards idle through the probe window so sockets stay realistic.
        await sleep_until(schedule["reconnect_at"] + 5.0 + SLOW_PROBE_S)

    for c in live:
        c.alive = False
        await c.close_sockets()
    await client.aclose()


def dump_shard_metrics(path: str):
    with open(path, "w") as f:
        json.dump({
            "rest_lat": {k: v for k, v in rest_lat.items()},
            "rest_status": {k: dict(v) for k, v in rest_status.items()},
            "submit_correct_lat": submit_correct_lat,
            "ws_connect_lat": {k: v for k, v in ws_connect_lat.items()},
            "ws_frames": dict(ws_frames),
            "ws_errs": dict(ws_errs),
            "counters": dict(counters),
            "probe_lags": probe_lags,
            "comp_events": comp_events,
            "timeline": timeline,
        }, f)


def load_shard_metrics(path: str):
    with open(path) as f:
        d = json.load(f)
    for k, v in d["rest_lat"].items():
        rest_lat[k].extend(v)
    for k, v in d["rest_status"].items():
        rest_status[k].update(v)
    submit_correct_lat.extend(d["submit_correct_lat"])
    for k, v in d["ws_connect_lat"].items():
        ws_connect_lat[k].extend(v)
    ws_frames.update(d["ws_frames"])
    ws_errs.update(d["ws_errs"])
    counters.update(d["counters"])
    probe_lags.extend(d["probe_lags"])
    comp_events.extend(d["comp_events"])
    timeline.extend(d["timeline"])


# ---- orchestration -----------------------------------------------------------
async def main():
    global HTTP, WS, T0
    split = comp_split()

    if RANK >= 0:
        # ---- worker: read bootstrap, run my slice, dump metrics --------------
        with open(os.environ["BOOT"]) as f:
            boot = json.load(f)
        HTTP, WS = boot["http"], boot["ws"]
        T0 = boot["schedule"]["t0"]
        my_indices = [i for i in range(N_USERS) if i % SHARDS == RANK]
        await run_clients(boot["comps"], boot["admin_token"], boot["schedule"],
                          my_indices, split, is_rank0=(RANK == 0))
        dump_shard_metrics(os.environ["OUT"])
        return

    # ---- parent (or single-process run) --------------------------------------
    async with httpx.AsyncClient() as probe:
        for h, w, label in [(HTTP_CADDY, WS_CADDY, "Caddy :8080"), (HTTP_DIRECT, WS_DIRECT, "direct :8001")]:
            try:
                r = await probe.get(h + "/api/health", timeout=5)
                if r.status_code == 200:
                    HTTP, WS = h, w
                    note(f"endpoint: {label}")
                    break
            except Exception:  # noqa: BLE001
                continue
    if not HTTP:
        note("no reachable endpoint — is the stack up?")
        return

    T0 = time.time()
    boot_client = httpx.AsyncClient(limits=httpx.Limits(max_connections=16))
    comps, admin_token = await bootstrap(boot_client)
    await boot_client.aclose()

    start = time.time() + 3.0
    schedule = {
        "t0": T0,
        "doors_end": start + DOORS_OPEN_S,
        "announce_at": start + DOORS_OPEN_S + ANNOUNCE_AT_S,
        "steady_end": start + DOORS_OPEN_S + STEADY_S,
        "burst_end": start + DOORS_OPEN_S + STEADY_S + BURST_S,
        "reconnect_at": start + DOORS_OPEN_S + STEADY_S + BURST_S + 3.0,
    }

    stop = asyncio.Event()

    if SHARDS <= 1:
        sampler = asyncio.create_task(sample_resources(stop, [os.getpid()]))
        await run_clients(comps, admin_token, schedule,
                          list(range(N_USERS)), split, is_rank0=True)
    else:
        outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".shards")
        os.makedirs(outdir, exist_ok=True)
        boot_path = os.path.join(outdir, "boot.json")
        with open(boot_path, "w") as f:
            json.dump({"http": HTTP, "ws": WS, "comps": comps,
                       "admin_token": admin_token, "schedule": schedule}, f)

        procs = []
        for k in range(SHARDS):
            env = dict(os.environ, RANK=str(k), BOOT=boot_path,
                       OUT=os.path.join(outdir, f"shard-{k}.json"))
            procs.append(await asyncio.create_subprocess_exec(
                sys.executable, os.path.abspath(__file__), env=env))
        note(f"spawned {SHARDS} shard workers for {N_USERS} users across {N_COMPS} comps "
             f"(split {split})")
        sampler = asyncio.create_task(sample_resources(stop, [p.pid for p in procs]))
        codes = await asyncio.gather(*(p.wait() for p in procs))
        note(f"shards exited: {codes}")
        for k in range(SHARDS):
            sp = os.path.join(outdir, f"shard-{k}.json")
            if os.path.exists(sp):
                load_shard_metrics(sp)
            else:
                note(f"WARNING shard {k} left no metrics file")

    stop.set()
    await sampler
    report(schedule, split)


# ---- report -------------------------------------------------------------------
def window_stats(events: list[list], comp: int, cls: str,
                 t_from: float, t_to: float) -> dict:
    xs = [e[3] for e in events
          if e[1] == comp and e[2] == cls and e[3] is not None and t_from <= e[0] < t_to]
    return {"n": len(xs), "p50": pct(xs, 50), "p95": pct(xs, 95)}


def report(schedule: dict, split: list[int]):
    def block(cls):
        xs = rest_lat.get(cls, [])
        return (f"  {cls:10s} n={len(xs):5d}  p50={pct(xs,50):7.0f}ms  p95={pct(xs,95):7.0f}ms  "
                f"p99={pct(xs,99):7.0f}ms  max={max(xs) if xs else 0:7.0f}ms  status={dict(rest_status[cls])}")

    cpu_vals = [float(s["cpu"].rstrip('%')) for s in resource_samples if s.get("cpu") and s["cpu"].endswith('%')]
    pg_vals = [int(s["pg_conns"]) for s in resource_samples if (s.get("pg_conns") or "").isdigit()]
    harness_vals = [s["harness_cpu"] for s in resource_samples if s.get("harness_cpu") is not None]

    lines = []
    lines.append("=" * 78)
    lines.append(f"FLAGPOST CAPACITY SIMULATION — {'SMOKE' if SMOKE else 'FULL'} RUN")
    lines.append("=" * 78)
    lines.append(f"users={N_USERS} comps={N_COMPS} split={split} shards={SHARDS} "
                 f"challenges/comp={N_CHALLENGES} endpoint={HTTP}")
    lines.append("")
    lines.append("REST latency by class (all competitions):")
    for cls in ["setup", "login", "join", "admin", "import", "submit", "refetch", "announce"]:
        if rest_lat.get(cls):
            lines.append(block(cls))
    lines.append("")
    lines.append("Submissions:")
    lines.append(f"  attempts={counters['attempts']} solves={counters['solves']} "
                 f"429s={counters['submit_429']} login_fail={counters['login_fail']}")
    lines.append(f"  correct-solve submit latency: p50={pct(submit_correct_lat,50):.0f}ms "
                 f"p95={pct(submit_correct_lat,95):.0f}ms p99={pct(submit_correct_lat,99):.0f}ms "
                 f"max={max(submit_correct_lat) if submit_correct_lat else 0:.0f}ms")
    lines.append("")

    if N_COMPS > 1:
        lines.append("Per-competition (whole run):")
        for ci in range(N_COMPS):
            sub = window_stats(comp_events, ci, "submit", 0, float("inf"))
            ref = window_stats(comp_events, ci, "refetch", 0, float("inf"))
            lines.append(f"  comp{ci} users={split[ci]:4d} solves={counters[f'solves_c{ci}']:5d} "
                         f"attempts={counters[f'attempts_c{ci}']:6d}  "
                         f"submit p50/p95={sub['p50']:.0f}/{sub['p95']:.0f}ms  "
                         f"refetch p50/p95={ref['p50']:.0f}/{ref['p95']:.0f}ms")
        lines.append("")
        lines.append("Tenancy isolation — quiet comps during comp-0 burst vs steady:")
        s0, s1 = schedule["doors_end"], schedule["steady_end"]
        b0, b1 = schedule["steady_end"], schedule["burst_end"]
        for ci in range(1, N_COMPS):
            st = window_stats(comp_events, ci, "refetch", s0, s1)
            bu = window_stats(comp_events, ci, "refetch", b0, b1)
            sts = window_stats(comp_events, ci, "submit", s0, s1)
            bus = window_stats(comp_events, ci, "submit", b0, b1)
            lines.append(f"  comp{ci}: refetch p50 {st['p50']:.0f} -> {bu['p50']:.0f}ms "
                         f"(p95 {st['p95']:.0f} -> {bu['p95']:.0f}ms, n={st['n']}->{bu['n']}) | "
                         f"submit p50 {sts['p50']:.0f} -> {bus['p50']:.0f}ms "
                         f"(p95 {sts['p95']:.0f} -> {bus['p95']:.0f}ms)")
        hot_st = window_stats(comp_events, 0, "submit", s0, s1)
        hot_bu = window_stats(comp_events, 0, "submit", b0, b1)
        lines.append(f"  comp0 (hot): submit p50 {hot_st['p50']:.0f} -> {hot_bu['p50']:.0f}ms "
                     f"(p95 {hot_st['p95']:.0f} -> {hot_bu['p95']:.0f}ms, n={hot_st['n']}->{hot_bu['n']})")
        lines.append("")

    lines.append("WebSockets:")
    for rt in ["scoreboard", "activity", "announcements", "user", "challenge"]:
        if ws_connect_lat.get(rt):
            xs = ws_connect_lat[rt]
            lines.append(f"  connect {rt:12s} n={len(xs):5d} p50={pct(xs,50):.0f}ms "
                         f"p95={pct(xs,95):.0f}ms max={max(xs):.0f}ms")
    lines.append(f"  frames received: {dict(ws_frames)}")
    lines.append(f"  ws errors: {dict(ws_errs)}")
    lines.append("")
    lines.append("Phase 5 slow-client probe (submit latency incl. scoreboard broadcast path):")
    lines.append(f"  probes={len(probe_lags)} p50={pct(probe_lags,50):.0f}ms "
                 f"p95={pct(probe_lags,95):.0f}ms max={max(probe_lags) if probe_lags else 0:.0f}ms")
    lines.append("")
    lines.append("Backend resource usage (docker stats sampled @3s):")
    lines.append(f"  CPU%: p50={pct(cpu_vals,50):.0f} p95={pct(cpu_vals,95):.0f} max={max(cpu_vals) if cpu_vals else 0:.0f}"
                 f"  (limit 400% = 4 cores)")
    lines.append(f"  Postgres connections: max={max(pg_vals) if pg_vals else 0} "
                 f"(configured cap = db_pool_size + db_max_overflow; 60 in current defaults)")
    if harness_vals:
        lines.append(f"  Harness CPU% (all shards): p50={pct(harness_vals,50):.0f} "
                     f"max={max(harness_vals):.0f}  (honest-limits telemetry: >~{SHARDS*90} "
                     f"means client-side tails are queueing artifacts)")
    lines.append("=" * 78)

    text = "\n".join(lines)
    print("\n" + text)
    out = {
        "config": {"users": N_USERS, "comps": N_COMPS, "split": split, "shards": SHARDS,
                   "challenges_per_comp": N_CHALLENGES, "endpoint": HTTP, "smoke": SMOKE},
        "schedule": schedule,
        "rest_latency": {c: {"n": len(rest_lat[c]), "p50": pct(rest_lat[c], 50), "p95": pct(rest_lat[c], 95),
                             "p99": pct(rest_lat[c], 99), "max": max(rest_lat[c]) if rest_lat[c] else 0,
                             "status": dict(rest_status[c])} for c in rest_lat},
        "submissions": {"attempts": counters["attempts"], "solves": counters["solves"],
                        "http_429": counters["submit_429"],
                        "per_comp": {f"c{ci}": {"attempts": counters[f"attempts_c{ci}"],
                                                "solves": counters[f"solves_c{ci}"]}
                                     for ci in range(N_COMPS)},
                        "correct_submit_lat": {"p50": pct(submit_correct_lat, 50), "p95": pct(submit_correct_lat, 95),
                                               "p99": pct(submit_correct_lat, 99),
                                               "max": max(submit_correct_lat) if submit_correct_lat else 0}},
        "isolation": {
            f"c{ci}": {
                "steady": window_stats(comp_events, ci, "refetch", schedule["doors_end"], schedule["steady_end"]),
                "burst": window_stats(comp_events, ci, "refetch", schedule["steady_end"], schedule["burst_end"]),
                "steady_submit": window_stats(comp_events, ci, "submit", schedule["doors_end"], schedule["steady_end"]),
                "burst_submit": window_stats(comp_events, ci, "submit", schedule["steady_end"], schedule["burst_end"]),
            } for ci in range(N_COMPS)
        } if N_COMPS > 1 else {},
        "ws": {"connect_lat": {rt: {"p50": pct(v, 50), "p95": pct(v, 95), "max": max(v)}
                               for rt, v in ws_connect_lat.items()},
               "frames": dict(ws_frames), "errors": dict(ws_errs)},
        "probe_lags_ms": {"p50": pct(probe_lags, 50), "p95": pct(probe_lags, 95),
                          "max": max(probe_lags) if probe_lags else 0, "n": len(probe_lags)},
        "resources": {"cpu_pct": {"p50": pct(cpu_vals, 50), "p95": pct(cpu_vals, 95),
                                  "max": max(cpu_vals) if cpu_vals else 0},
                      "pg_conns_max": max(pg_vals) if pg_vals else 0,
                      "harness_cpu_max": max(harness_vals) if harness_vals else None,
                      "samples": resource_samples},
        "timeline": sorted(timeline),
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim-result.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nJSON: {path}")


if __name__ == "__main__":
    asyncio.run(main())
