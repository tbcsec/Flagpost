"""Demo activity simulator — makes the public demo (demo.flagpost.io) feel *live*.

Runs as its own process on the demo host (a service in ``docker-compose.demo.yml``)
and drives realistic traffic against the real HTTP API the same way competitors
do: rolling new sign-ups, correct **and** incorrect flag submissions (correct ones
move the live scoreboard over WebSocket, some earning first bloods), support
tickets with competitor and staff replies. The point is to advertise the
platform's live nature to anyone watching, without getting in the way of a
visitor exploring the demo.

**Demo-only, by design and by guard.** It refuses to run unless (a) ``DEMO_SIMULATOR``
is truthy and (b) the target instance reports ``demo_mode`` on its public site
settings — so it can never hammer a real deployment. Every competitor it creates
is a fresh, throwaway bot (wiped by the hourly reset); it never acts *as* the
well-known ``admin`` / ``judge`` / ``participant`` accounts a visitor logs in as,
beyond read-only discovery and provisioning one dedicated ``support_bot`` staff
account. Staff actions are scoped strictly to tickets the bots themselves opened
(tracked by id), so a real visitor's ticket is never touched, replied to, or
resolved.

Run::

    DEMO_SIMULATOR=1 SIM_BASE_URL=http://backend:8000 python demo_simulator.py

Tunables (all env, all optional) — see the constants below.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import sys

import httpx

from auth.demo_data import (
    DEMO_COMPETITION_NAME,
    DEMO_PASSWORD,
    DEMO_SOLUTIONS,
    DEMO_WRONG_FLAGS,
)

log = logging.getLogger("demo_simulator")


# --- Config ------------------------------------------------------------------
def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _flag(name: str, default: str = "0") -> bool:
    return _env(name, default).strip().lower() in ("1", "true", "yes", "on")


ENABLED = _flag("DEMO_SIMULATOR", "0")
BASE_URL = _env("SIM_BASE_URL", "http://backend:8000").rstrip("/")
COMPETITION_NAME = _env("SIM_COMPETITION_NAME", DEMO_COMPETITION_NAME)
VERIFY_DEMO = _flag("SIM_VERIFY_DEMO", "1")
ENABLE_STAFF = _flag("SIM_ENABLE_STAFF", "1")

# Pacing. Intervals are averages; each wait is jittered ±50 % so the traffic
# looks organic rather than metronomic. Defaults are deliberately gentle — a
# handful of actions a minute, visibly live without being a flood.
MAX_ACTIVE_BOTS = int(_env("SIM_MAX_ACTIVE_BOTS", "12"))
SIGNUP_INTERVAL = float(_env("SIM_SIGNUP_INTERVAL", "25"))  # seconds between sign-ups
ACTION_INTERVAL = float(_env("SIM_ACTION_INTERVAL", "5"))  # seconds between competitor actions
STAFF_INTERVAL = float(_env("SIM_STAFF_INTERVAL", "40"))  # seconds between staff actions

# All bots share one password (they only exist for the demo, and get wiped
# hourly). ≥ 8 chars to satisfy the register/create-user policy.
BOT_PASSWORD = _env("SIM_BOT_PASSWORD", "sim-demo-bot-pw")
STAFF_NAME = _env("SIM_STAFF_NAME", "support_bot")
# Read-only discovery + staff provisioning use the seeded demo admin.
ADMIN_IDENTIFIER = _env("SIM_ADMIN_IDENTIFIER", "admin")
ADMIN_PASSWORD = _env("SIM_ADMIN_PASSWORD", DEMO_PASSWORD)


# --- Flavour data ------------------------------------------------------------
_ADJ = [
    "neon", "shadow", "quantum", "binary", "crimson", "silent", "hyper", "void",
    "cyber", "rusty", "glitch", "turbo", "zero", "lunar", "atomic", "phantom",
    "frost", "pixel", "hollow", "static", "ember", "nova",
]
_NOUN = [
    "raptor", "cipher", "byte", "phoenix", "wolf", "hacker", "ninja", "fox",
    "specter", "daemon", "circuit", "viper", "comet", "golem", "falcon", "kraken",
    "ronin", "sentry", "matrix", "vortex", "banshee", "hydra",
]

_TICKET_SUBJECTS = [
    "Stuck on {title}",
    "Hint for {title}?",
    "Is {title} working?",
    "Flag format on {title}",
    "{title} — am I close?",
]
_TICKET_BODIES = [
    "I've been on {title} for a while — any nudge in the right direction?",
    "Is the flag format for {title} the usual flag{{...}}?",
    "I think I'm close on {title} but my submissions keep failing. Any help?",
    "Does {title} need anything beyond what's in the description?",
    "Just want to confirm {title} is solvable as-is — thanks!",
]
_COMPETITOR_REPLIES = [
    "Never mind — got it! Thanks.",
    "Still stuck, any other hints?",
    "That pointed me the right way, thank you!",
    "Ah, I was overcomplicating it.",
    "Appreciate the quick response.",
]
_STAFF_REPLIES = [
    "Thanks for reaching out! Take another look at the challenge description — "
    "the hint's closer than you think.",
    "Good question — the flag format is the standard flag{{...}}. You're on the "
    "right track.",
    "Happy to help. The title is a strong clue here. Let us know if you're still "
    "stuck!",
    "We've checked and it's working as intended. Keep at it — you're close!",
]


def _make_handle() -> str:
    return f"{random.choice(_ADJ)}{random.choice(_NOUN)}{random.randint(1, 999)}"


def _jitter(mean: float) -> float:
    return random.uniform(mean * 0.5, mean * 1.5)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Shared state ------------------------------------------------------------
class Sim:
    def __init__(self, competition_id: str) -> None:
        self.competition_id = competition_id
        self.challenges: list[dict] = []  # {id, title, flag_type, choices, locked}
        self.bots: list[dict] = []  # active competitors: {token, name, solved:set, tickets:list}
        self.bot_ticket_ids: set[str] = set()  # tickets opened by bots (staff acts only on these)
        self.staff: dict | None = None  # {token, name} or None


# --- API helpers -------------------------------------------------------------
async def _wait_for_api(client: httpx.AsyncClient) -> None:
    for _ in range(150):
        try:
            r = await client.get(f"{BASE_URL}/api/health")
            if r.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2)
    raise RuntimeError(f"API at {BASE_URL} never became reachable")


async def _is_demo(client: httpx.AsyncClient) -> bool:
    try:
        r = await client.get(f"{BASE_URL}/api/site-settings")
        return r.status_code == 200 and bool(r.json().get("demo_mode"))
    except httpx.HTTPError:
        return False


async def _discover_competition(client: httpx.AsyncClient) -> str:
    for _ in range(60):
        try:
            r = await client.get(f"{BASE_URL}/api/public/competitions")
            if r.status_code == 200:
                for comp in r.json():
                    if comp.get("name") == COMPETITION_NAME:
                        return comp["id"]
        except httpx.HTTPError:
            pass
        await asyncio.sleep(2)
    raise RuntimeError(f"demo competition {COMPETITION_NAME!r} not found in /api/public/competitions")


async def _register_and_join(client: httpx.AsyncClient, competition_id: str) -> dict | None:
    """Register a fresh competitor bot (no email — it's optional) and join the
    public competition, returning its session, or None on failure."""
    for _ in range(3):
        name = _make_handle()
        try:
            r = await client.post(
                f"{BASE_URL}/api/auth/register",
                json={"display_name": name, "password": BOT_PASSWORD},
            )
        except httpx.HTTPError as exc:
            log.debug("register error: %s", exc)
            return None
        if r.status_code == 201:
            token = r.json()["access_token"]
            try:
                await client.post(
                    f"{BASE_URL}/api/competitions/{competition_id}/join",
                    headers=_auth(token),
                )
            except httpx.HTTPError as exc:
                log.debug("join error: %s", exc)
                return None
            return {"token": token, "name": name, "solved": set(), "tickets": []}
        if r.status_code == 409:
            continue  # handle clash — try another
        log.debug("register failed %s: %s", r.status_code, r.text[:120])
        return None
    return None


async def _fetch_challenges(client: httpx.AsyncClient, token: str, competition_id: str) -> list[dict]:
    r = await client.get(
        f"{BASE_URL}/api/competitions/{competition_id}/challenges", headers=_auth(token)
    )
    if r.status_code != 200:
        return []
    return [
        {
            "id": c["id"],
            "title": c["title"],
            "flag_type": c.get("flag_type"),
            "choices": c.get("choices"),
            "locked": c.get("locked", False),
        }
        for c in r.json()
    ]


async def _provision_staff(client: httpx.AsyncClient, competition_id: str) -> dict | None:
    """Create a dedicated Judge bot (so the shared demo ``judge`` stays free for
    visitors) and return its session. Best-effort — returns None if any step fails."""
    try:
        r = await client.post(
            f"{BASE_URL}/api/auth/login",
            json={"identifier": ADMIN_IDENTIFIER, "password": ADMIN_PASSWORD},
        )
        if r.status_code != 200:
            log.warning("staff: admin login failed (%s) — no staff bot", r.status_code)
            return None
        admin = r.json()["access_token"]

        # Create the account (409 = already there from an earlier boot; fine).
        r = await client.post(
            f"{BASE_URL}/api/users",
            headers=_auth(admin),
            json={"display_name": STAFF_NAME, "password": BOT_PASSWORD},
        )
        if r.status_code not in (201, 409):
            log.warning("staff: create user failed (%s)", r.status_code)
            return None

        r = await client.get(f"{BASE_URL}/api/roles", headers=_auth(admin))
        if r.status_code != 200:
            return None
        judge_id = next((role["id"] for role in r.json() if role["name"] == "Judge"), None)
        if not judge_id:
            return None

        # Assign Judge on the demo competition (the ``email`` field resolves by
        # username too, ADR-0015; 409 = already assigned).
        await client.post(
            f"{BASE_URL}/api/roles/assignments",
            headers=_auth(admin),
            json={"email": STAFF_NAME, "role_id": judge_id, "competition_id": competition_id},
        )

        r = await client.post(
            f"{BASE_URL}/api/auth/login",
            json={"identifier": STAFF_NAME, "password": BOT_PASSWORD},
        )
        if r.status_code != 200:
            return None
        return {"token": r.json()["access_token"], "name": STAFF_NAME}
    except httpx.HTTPError as exc:
        log.warning("staff provisioning error: %s", exc)
        return None


# --- Competitor actions ------------------------------------------------------
async def _act_solve(client: httpx.AsyncClient, sim: Sim, bot: dict) -> None:
    unsolved = [
        c for c in sim.challenges
        if c["title"] in DEMO_SOLUTIONS and c["id"] not in bot["solved"] and not c["locked"]
    ]
    if not unsolved:
        return await _act_wrong(client, sim, bot)  # solved everything → keep them active with a miss
    c = random.choice(unsolved)
    r = await client.post(
        f"{BASE_URL}/api/competitions/{sim.competition_id}/challenges/{c['id']}/submit",
        headers=_auth(bot["token"]),
        json={"flag": DEMO_SOLUTIONS[c["title"]]},
    )
    if r.status_code == 200 and r.json().get("correct"):
        bot["solved"].add(c["id"])
        res = r.json()
        log.info(
            "solve  %-16s %-20s +%d%s",
            bot["name"], c["title"], res.get("points_awarded", 0),
            "  [FIRST BLOOD]" if res.get("is_first_blood") else "",
        )


async def _act_wrong(client: httpx.AsyncClient, sim: Sim, bot: dict) -> None:
    unsolved = [c for c in sim.challenges if c["id"] not in bot["solved"] and not c["locked"]]
    if not unsolved:
        return
    c = random.choice(unsolved)
    if c["flag_type"] == "multiple_choice" and c.get("choices"):
        wrong = [ch for ch in c["choices"] if ch != DEMO_SOLUTIONS.get(c["title"])]
        guess = random.choice(wrong) if wrong else "nope"
    else:
        guess = random.choice(DEMO_WRONG_FLAGS)
    await client.post(
        f"{BASE_URL}/api/competitions/{sim.competition_id}/challenges/{c['id']}/submit",
        headers=_auth(bot["token"]),
        json={"flag": guess},
    )


async def _act_ticket(client: httpx.AsyncClient, sim: Sim, bot: dict) -> None:
    if len(bot["tickets"]) >= 2 or not sim.challenges:
        return  # one or two tickets per bot — no spamming the queue
    c = random.choice(sim.challenges)
    r = await client.post(
        f"{BASE_URL}/api/competitions/{sim.competition_id}/tickets",
        headers=_auth(bot["token"]),
        json={
            "subject": random.choice(_TICKET_SUBJECTS).format(title=c["title"]),
            "body": random.choice(_TICKET_BODIES).format(title=c["title"]),
            "challenge_id": c["id"],
        },
    )
    if r.status_code in (200, 201):
        tid = r.json()["id"]
        bot["tickets"].append(tid)
        sim.bot_ticket_ids.add(tid)
        log.info("ticket %-16s opened a ticket", bot["name"])


async def _act_reply(client: httpx.AsyncClient, sim: Sim, bot: dict) -> None:
    if not bot["tickets"]:
        return
    tid = random.choice(bot["tickets"])
    await client.post(
        f"{BASE_URL}/api/competitions/{sim.competition_id}/tickets/{tid}/messages",
        headers=_auth(bot["token"]),
        json={"body": random.choice(_COMPETITOR_REPLIES)},
    )


async def _do_action(client: httpx.AsyncClient, sim: Sim, bot: dict) -> None:
    # Solves dominate — they're the headline "live" signal (scoreboard movement).
    action = random.choices(
        ["solve", "wrong", "ticket", "reply"], weights=[6, 3, 1, 1]
    )[0]
    handler = {
        "solve": _act_solve, "wrong": _act_wrong,
        "ticket": _act_ticket, "reply": _act_reply,
    }[action]
    try:
        await handler(client, sim, bot)
    except httpx.HTTPError as exc:
        log.debug("action %s failed for %s: %s", action, bot["name"], exc)


# --- Loops -------------------------------------------------------------------
async def _signup_loop(client: httpx.AsyncClient, sim: Sim) -> None:
    while True:
        await asyncio.sleep(_jitter(SIGNUP_INTERVAL))
        # Retire the oldest bot when at capacity so there's a *steady* stream of
        # new sign-ups (the account itself lingers until the hourly reset).
        if len(sim.bots) >= MAX_ACTIVE_BOTS:
            sim.bots.pop(0)
        bot = await _register_and_join(client, sim.competition_id)
        if bot:
            sim.bots.append(bot)
            log.info("signup %-16s joined (%d active)", bot["name"], len(sim.bots))


async def _activity_loop(client: httpx.AsyncClient, sim: Sim) -> None:
    while True:
        await asyncio.sleep(_jitter(ACTION_INTERVAL))
        if sim.bots:
            await _do_action(client, sim, random.choice(sim.bots))


async def _staff_loop(client: httpx.AsyncClient, sim: Sim) -> None:
    if not sim.staff:
        return
    while True:
        await asyncio.sleep(_jitter(STAFF_INTERVAL))
        try:
            r = await client.get(
                f"{BASE_URL}/api/competitions/{sim.competition_id}/tickets",
                headers=_auth(sim.staff["token"]),
            )
            if r.status_code != 200:
                continue
            # Strictly bot-opened, not-yet-resolved tickets — never a visitor's.
            candidates = [
                t for t in r.json()
                if t["id"] in sim.bot_ticket_ids and t.get("status") != "resolved"
            ]
            if not candidates:
                continue
            t = random.choice(candidates)
            await client.post(
                f"{BASE_URL}/api/competitions/{sim.competition_id}/tickets/{t['id']}/messages",
                headers=_auth(sim.staff["token"]),
                json={"body": random.choice(_STAFF_REPLIES)},
            )
            log.info("staff  replied to a ticket")
            if random.random() < 0.4:
                await client.post(
                    f"{BASE_URL}/api/competitions/{sim.competition_id}/tickets/{t['id']}/resolve",
                    headers=_auth(sim.staff["token"]),
                )
        except httpx.HTTPError as exc:
            log.debug("staff action failed: %s", exc)


# --- Entrypoint --------------------------------------------------------------
async def run() -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        log.info("waiting for API at %s …", BASE_URL)
        await _wait_for_api(client)

        if VERIFY_DEMO and not await _is_demo(client):
            log.error(
                "target %s is NOT a demo instance (demo_mode is false) — refusing "
                "to run. Set SIM_VERIFY_DEMO=0 only if you are certain.", BASE_URL,
            )
            return

        competition_id = await _discover_competition(client)
        sim = Sim(competition_id)

        # Seed one bot up front so we can read the challenge list (needs a member).
        seed_bot = await _register_and_join(client, competition_id)
        if seed_bot:
            sim.bots.append(seed_bot)
            sim.challenges = await _fetch_challenges(client, seed_bot["token"], competition_id)
        if not sim.challenges:
            log.error("no visible challenges — nothing to simulate against; exiting")
            return

        if ENABLE_STAFF:
            sim.staff = await _provision_staff(client, competition_id)

        # A small opening burst so the instance looks active immediately.
        for _ in range(4):
            bot = await _register_and_join(client, competition_id)
            if bot:
                sim.bots.append(bot)

        log.info(
            "simulator live — competition=%s challenges=%d staff=%s starting=%d bots",
            competition_id, len(sim.challenges), bool(sim.staff), len(sim.bots),
        )
        await asyncio.gather(
            _signup_loop(client, sim),
            _activity_loop(client, sim),
            _staff_loop(client, sim),
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    if not ENABLED:
        log.info("DEMO_SIMULATOR is not set — nothing to do (demo instances only). Exiting.")
        return
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
