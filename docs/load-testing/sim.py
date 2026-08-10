"""Flagpost 200-user live-event capacity simulation (issue-less capacity review).

Drives the REAL production docker stack (Caddy -> single-process backend ->
Postgres/Redis/MinIO) with 200 simulated competitors, each behaving like a
browser: 4 shell WebSockets (scoreboard, activity, announcements, user) held
open, plus transient challenge-presence sockets while "viewing" a challenge, and
— crucially — the exact frontend refetch behaviour (lib/live.ts): an activity
ping maps to query keys, each on a 2.5s leading+trailing throttle, and only the
keys mounted by the client's current page trigger a real REST GET.

Five phases: doors-open login+connect storm, steady play, announcement blast,
reconnect herd, slow-client head-of-line probe. Emits a JSON + text report.

Run:  .venv/bin/python sim.py            (full 200-user run)
      SMOKE=1 .venv/bin/python sim.py    (10-user harness self-test)
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import statistics
import time
from collections import Counter, defaultdict

import httpx
import websockets

SMOKE = os.environ.get("SMOKE") == "1"

# ---- knobs ------------------------------------------------------------------
N_USERS = 10 if SMOKE else 200
N_CHALLENGES = 6 if SMOKE else 30
N_DYNAMIC = 2 if SMOKE else 10  # of N_CHALLENGES, the rest static
USER_PW = "loadtest-passw0rd"

DOORS_OPEN_S = 15 if SMOKE else 120
STEADY_S = 40 if SMOKE else 300
ANNOUNCE_AT_S = 20 if SMOKE else 240      # offset into steady
RECONNECT_AT_S = None                      # set = doors+steady (after steady)
SLOW_PROBE_S = 20 if SMOKE else 80

SUBMIT_MIN_GAP, SUBMIT_MAX_GAP = (3.0, 9.0) if SMOKE else (6.0, 15.0)
CORRECT_FRACTION = 0.25                    # of submissions that use a real flag
NAV_MIN_GAP, NAV_MAX_GAP = (8.0, 20.0)
PRESENCE_VIEW_MIN, PRESENCE_VIEW_MAX = (6.0, 14.0)
N_SLOW_CLIENTS = 3 if SMOKE else 8

ADMIN = {"display_name": "loadadmin", "email": "loadadmin@example.com", "password": "loadadmin-passw0rd"}
COMP_NAME = "Load Test Open 2026"

# ---- endpoints --------------------------------------------------------------
HTTP_CADDY, WS_CADDY = "http://localhost:8080", "ws://localhost:8080"
HTTP_DIRECT, WS_DIRECT = "http://localhost:8001", "ws://localhost:8001"
HTTP = WS = ""  # resolved in main()

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


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(round((p / 100) * (len(xs) - 1)))))
    return xs[k]


def note(msg: str) -> None:
    stamp = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(stamp, flush=True)
    timeline.append(stamp)


# ---- activity -> query-key -> REST mapping (mirrors frontend/src/lib/live.ts)-
def _dash(cid):
    return [("dashboard", cid, "stats"), ("dashboard", cid, "recent-solves"),
            ("dashboard", cid, "challenge-health"), ("dashboard", cid, "me")]


def keys_for_activity(event: str, cid: str) -> list[tuple]:
    if event == "challenge.solved":
        return [("challenges", cid), *_dash(cid), ("analytics", cid), ("participants", cid)]
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
              token: str | None = None, **kw) -> httpx.Response | None:
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    t0 = time.monotonic()
    try:
        r = await client.request(method, HTTP + path, headers=headers, timeout=30, **kw)
    except Exception as e:  # noqa: BLE001
        rest_status[cls][type(e).__name__] += 1
        return None
    rest_lat[cls].append((time.monotonic() - t0) * 1000)
    rest_status[cls][r.status_code] += 1
    return r


# ---- bootstrap (admin) ------------------------------------------------------
async def bootstrap(client: httpx.AsyncClient) -> tuple[str, list[dict]]:
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

    # 2. Competition (individual, public, always-on).
    r = await req(client, "POST", "/api/competitions", "admin", token=token, json={
        "name": COMP_NAME, "participation_mode": "individual", "visibility": "public",
    })
    cid = r.json()["id"]
    note(f"competition {cid}")

    # 3. Challenges (mix of static + dynamic decay), each published with a known flag.
    challenges = []
    for i in range(N_CHALLENGES):
        dynamic = i < N_DYNAMIC
        flag = f"flag{{loadtest-{i:03d}}}"
        body = {"title": f"Challenge {i:03d}", "flag_type": "static", "flag": flag, "points": 500}
        if dynamic:
            body.update({"scoring_type": "dynamic", "min_points": 100, "decay": 50})
        r = await req(client, "POST", f"/api/competitions/{cid}/challenges", "admin", token=token, json=body)
        chid = r.json()["id"]
        await req(client, "POST", f"/api/competitions/{cid}/challenges/{chid}/publish", "admin", token=token)
        challenges.append({"id": chid, "flag": flag})
    note(f"created + published {len(challenges)} challenges ({N_DYNAMIC} dynamic)")

    # 4. Import 200 accounts via the mass-import CSV (dogfoods #171). No roles —
    #    each self-joins in phase 1 (the real doors-open path).
    lines = ["display_name,password"] + [f"loadtest{n:04d},{USER_PW}" for n in range(N_USERS)]
    csv = ("\n".join(lines) + "\n").encode()
    r = await req(client, "POST", "/api/users/import", "admin", token=token,
                  files={"file": ("roster.csv", csv, "text/csv")})
    rep = r.json()
    note(f"user import: created={rep['created']} skipped={rep['skipped']} errors={rep['errors']}")
    return cid, challenges, token


# ---- client -----------------------------------------------------------------
class Client:
    def __init__(self, idx: int, client: httpx.AsyncClient, cid: str, challenges: list[dict]):
        self.idx = idx
        self.name = f"loadtest{idx:04d}"
        self.http = client
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
        await req(self.http, "POST", f"/api/competitions/{self.cid}/join", "join", token=self.token)

    async def initial_fetch(self):
        for key in self.mounts:
            p = key_to_path(key, self.cid)
            if p:
                await req(self.http, "GET", p, "refetch", token=self.token)

    async def _refetch(self, key: tuple):
        if key in self.mounts:
            p = key_to_path(key, self.cid)
            if p:
                await req(self.http, "GET", p, "refetch", token=self.token)

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
        r = await req(self.http, "POST", path, "submit", token=self.token, json={"flag": flag})
        if r is None:
            return
        counters["attempts"] += 1
        if r.status_code == 429:
            counters["submit_429"] += 1
            return
        if r.status_code == 200 and r.json().get("correct"):
            dt = (time.monotonic() - t0) * 1000
            if not r.json().get("already_solved"):
                self.solved.add(ch["id"])
                counters["solves"] += 1
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

    async def steady(self, until: float):
        async def submit_loop():
            while self.alive and time.monotonic() < until:
                await asyncio.sleep(random.uniform(SUBMIT_MIN_GAP, SUBMIT_MAX_GAP))
                await self.submit_once()

        async def nav_loop():
            while self.alive and time.monotonic() < until:
                await asyncio.sleep(random.uniform(NAV_MIN_GAP, NAV_MAX_GAP))
                self.page = random.choices(
                    ["challenges", "dashboard", "scoreboard", "participants"],
                    weights=[50, 30, 15, 5])[0]
                self.mounts = PAGE_MOUNTS[self.page](self.cid)
                await self.initial_fetch()

        async def presence_loop():
            while self.alive and time.monotonic() < until:
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


# ---- resource sampler -------------------------------------------------------
async def sample_resources(stop: asyncio.Event):
    name_backend = "flagpost-backend-1"
    name_pg = "flagpost-postgres-1"
    while not stop.is_set():
        cpu = mem = pg = None
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
        resource_samples.append({"t": round(time.monotonic() - T0, 1), "cpu": cpu, "mem": mem, "pg_conns": pg})
        try:
            await asyncio.wait_for(stop.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pass


# ---- phases -----------------------------------------------------------------
T0 = 0.0


async def main():
    global HTTP, WS, T0
    # resolve endpoint (prefer Caddy front door; fall back to direct backend)
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

    limits = httpx.Limits(max_connections=N_USERS * 2, max_keepalive_connections=N_USERS)
    client = httpx.AsyncClient(limits=limits)
    T0 = time.monotonic()

    cid, challenges, admin_token = await bootstrap(client)
    clients = [Client(i, client, cid, challenges) for i in range(N_USERS)]

    stop = asyncio.Event()
    sampler = asyncio.create_task(sample_resources(stop))

    # ---- Phase 1: doors open --------------------------------------------------
    note(f"PHASE 1 — doors open: {N_USERS} logins + {N_USERS*4} sockets + joins over {DOORS_OPEN_S}s")
    p1 = time.monotonic()

    async def onboard(c: Client, delay: float):
        await asyncio.sleep(delay)
        if not await c.login():
            return
        await c.join()
        await c.connect_shell()
        await c.initial_fetch()

    await asyncio.gather(*(onboard(c, random.uniform(0, DOORS_OPEN_S)) for c in clients))
    live = [c for c in clients if c.token and c.sockets]
    note(f"doors-open done in {time.monotonic()-p1:.1f}s — {len(live)}/{N_USERS} fully onboarded, "
         f"{sum(len(c.sockets) for c in clients)} sockets open")

    # ---- Phase 2: steady state (+ Phase 3 announcement mid-way) ---------------
    note(f"PHASE 2 — steady play for {STEADY_S}s (submits + navigation + presence churn)")
    until = time.monotonic() + STEADY_S

    async def announce_later():
        await asyncio.sleep(ANNOUNCE_AT_S)
        note("PHASE 3 — announcement blast to all participants")
        t0 = time.monotonic()
        r = await req(client, "POST", f"/api/competitions/{cid}/announcements", "announce",
                      token=admin_token, json={"title": "Load test broadcast",
                      "body": "All-participants announcement under load.", "severity": "info"})
        note(f"announcement POST -> {getattr(r,'status_code','ERR')} in {(time.monotonic()-t0)*1000:.0f}ms "
             f"(foreground fan-out to {len(live)} recipients)")

    await asyncio.gather(*(c.steady(until) for c in live), announce_later())
    note("steady state complete")

    # ---- Phase 4: reconnect herd ---------------------------------------------
    note("PHASE 4 — reconnect herd: dropping all sockets, reconnecting simultaneously")
    for c in live:
        await c.close_sockets()
    await asyncio.sleep(1.0)
    p4 = time.monotonic()

    async def reconnect(c: Client):
        await c.connect_shell()
        await c.initial_fetch()

    await asyncio.gather(*(reconnect(c) for c in live))
    note(f"reconnect herd done in {time.monotonic()-p4:.1f}s — "
         f"{sum(len(c.sockets) for c in live)} sockets re-established")

    # ---- Phase 5: slow-client head-of-line probe ------------------------------
    note(f"PHASE 5 — slow-client probe: {N_SLOW_CLIENTS} congested readers + solve burst")
    slow = live[:N_SLOW_CLIENTS]
    fast = live[N_SLOW_CLIENTS:2 * N_SLOW_CLIENTS + 20]
    # make the slow clients congested: reconnect their scoreboard socket in slow mode
    for c in slow:
        c.slow = True
        old = c.sockets.pop(f"scoreboard:{cid}", None)
        if old:
            await old.close()
        await c._open("scoreboard", cid)

    # probe: a fresh solver solves an unsolved challenge; measure how long until
    # the fast clients' scoreboard sockets receive their next frame.
    async def probe():
        end = time.monotonic() + SLOW_PROBE_S
        while time.monotonic() < end:
            solver = random.choice(fast) if fast else live[-1]
            unsolved = [ch for ch in challenges if ch["id"] not in solver.solved]
            if not unsolved:
                break
            ch = random.choice(unsolved)
            baseline = dict(ws_frames)
            t0 = time.monotonic()
            r = await req(client, "POST",
                          f"/api/competitions/{cid}/challenges/{ch['id']}/submit",
                          "submit", token=solver.token, json={"flag": ch["flag"]})
            if r is not None and r.status_code == 200 and r.json().get("correct"):
                solver.solved.add(ch["id"])
                # scoreboard broadcast should now fan out; record submit latency
                # (foreground includes the recompute+broadcast) as the signal.
                probe_lags.append((time.monotonic() - t0) * 1000)
            await asyncio.sleep(2.0)

    await probe()
    note(f"slow-client probe complete ({len(probe_lags)} probe solves)")

    # ---- teardown -------------------------------------------------------------
    stop.set()
    await sampler
    for c in live:
        c.alive = False
        await c.close_sockets()
    await client.aclose()

    report(cid)


def report(cid: str):
    def block(cls):
        xs = rest_lat.get(cls, [])
        return (f"  {cls:10s} n={len(xs):5d}  p50={pct(xs,50):7.0f}ms  p95={pct(xs,95):7.0f}ms  "
                f"p99={pct(xs,99):7.0f}ms  max={max(xs) if xs else 0:7.0f}ms  status={dict(rest_status[cls])}")

    cpu_vals = [float(s["cpu"].rstrip('%')) for s in resource_samples if s.get("cpu") and s["cpu"].endswith('%')]
    pg_vals = [int(s["pg_conns"]) for s in resource_samples if s.get("pg_conns", "").isdigit()]

    lines = []
    lines.append("=" * 78)
    lines.append(f"FLAGPOST 200-USER CAPACITY SIMULATION — {'SMOKE' if SMOKE else 'FULL'} RUN")
    lines.append("=" * 78)
    lines.append(f"users={N_USERS} challenges={N_CHALLENGES} endpoint={HTTP}")
    lines.append("")
    lines.append("REST latency by class:")
    for cls in ["setup", "login", "join", "admin", "submit", "refetch", "announce"]:
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
    lines.append("WebSockets:")
    for rt in ["scoreboard", "activity", "announcements", "user", "challenge"]:
        if ws_connect_lat.get(rt):
            xs = ws_connect_lat[rt]
            lines.append(f"  connect {rt:12s} n={len(xs):5d} p50={pct(xs,50):.0f}ms "
                         f"p95={pct(xs,95):.0f}ms max={max(xs):.0f}ms")
    lines.append(f"  frames received: {dict(ws_frames)}")
    lines.append(f"  ws errors: {dict(ws_errs)}")
    lines.append("")
    lines.append("Phase 5 slow-client probe (submit latency incl. foreground scoreboard broadcast):")
    lines.append(f"  probes={len(probe_lags)} p50={pct(probe_lags,50):.0f}ms "
                 f"p95={pct(probe_lags,95):.0f}ms max={max(probe_lags) if probe_lags else 0:.0f}ms")
    lines.append("")
    lines.append("Backend resource usage (docker stats sampled @3s):")
    lines.append(f"  CPU%: p50={pct(cpu_vals,50):.0f} p95={pct(cpu_vals,95):.0f} max={max(cpu_vals) if cpu_vals else 0:.0f}"
                 f"  (limit 400% = 4 cores)")
    lines.append(f"  Postgres connections: max={max(pg_vals) if pg_vals else 0} (pool_size 5 + overflow 10 = 15 cap)")
    lines.append("=" * 78)

    text = "\n".join(lines)
    print("\n" + text)
    out = {
        "config": {"users": N_USERS, "challenges": N_CHALLENGES, "endpoint": HTTP, "smoke": SMOKE},
        "rest_latency": {c: {"n": len(rest_lat[c]), "p50": pct(rest_lat[c], 50), "p95": pct(rest_lat[c], 95),
                             "p99": pct(rest_lat[c], 99), "max": max(rest_lat[c]) if rest_lat[c] else 0,
                             "status": dict(rest_status[c])} for c in rest_lat},
        "submissions": {"attempts": counters["attempts"], "solves": counters["solves"],
                        "http_429": counters["submit_429"],
                        "correct_submit_lat": {"p50": pct(submit_correct_lat, 50), "p95": pct(submit_correct_lat, 95),
                                               "p99": pct(submit_correct_lat, 99),
                                               "max": max(submit_correct_lat) if submit_correct_lat else 0}},
        "ws": {"connect_lat": {rt: {"p50": pct(v, 50), "p95": pct(v, 95), "max": max(v)}
                               for rt, v in ws_connect_lat.items()},
               "frames": dict(ws_frames), "errors": dict(ws_errs)},
        "probe_lags_ms": {"p50": pct(probe_lags, 50), "p95": pct(probe_lags, 95),
                          "max": max(probe_lags) if probe_lags else 0, "n": len(probe_lags)},
        "resources": {"cpu_pct": {"p50": pct(cpu_vals, 50), "p95": pct(cpu_vals, 95),
                                  "max": max(cpu_vals) if cpu_vals else 0},
                      "pg_conns_max": max(pg_vals) if pg_vals else 0,
                      "samples": resource_samples},
        "timeline": timeline,
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim-result.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nJSON: {path}")


if __name__ == "__main__":
    asyncio.run(main())
