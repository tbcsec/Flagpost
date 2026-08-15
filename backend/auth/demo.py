"""Demo-instance seed data (config.demo_mode).

For a public demo (e.g. demo.flagpost.io) that resets hourly. On startup — only
when ``settings.demo_mode`` is on — this seeds the well-known accounts the login
page advertises, plus a sample competition with challenges and a few solves so
the instance looks alive on first visit.

**Never runs outside demo mode** (it creates accounts with the password
``password``). Idempotent: if the demo admin already exists it does nothing, so a
plain restart doesn't duplicate data — the hourly *reset* (wiping the DB) is done
externally by the operator; a fresh boot then re-seeds.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.demo_data import (
    DEMO_COMPETITION_NAME,
    DEMO_PASSWORD,
    DEMO_SOLUTIONS,
    DEMO_WRONG_FLAGS,
)
from auth.security import hash_password
from auth.setup import mark_setup_complete
from models.automation import AutomationRule
from models.challenge import Category, Challenge
from models.competition import Competition, generate_invite_code
from models.hint import Hint
from models.role import Role, RoleAssignment
from models.submission import Submission
from models.user import User
from utils.flags import hash_static_flag, make_salt

# Re-exported from auth.demo_data (pure constants, importable without the ORM) so
# existing `from auth.demo import DEMO_*` call sites keep working.
__all__ = [
    "DEMO_COMPETITION_NAME",
    "DEMO_PASSWORD",
    "DEMO_SOLUTIONS",
    "DEMO_WRONG_FLAGS",
    "seed_demo_data",
]

# --- The sample competition's shape --------------------------------------------
DEMO_CATEGORIES = ("Web", "Crypto", "Pwn", "Reversing", "Forensics", "OSINT", "Misc")
DEMO_DIFFICULTY_TIERS = ["Easy", "Medium", "Hard", "Insane"]
DEMO_CHALLENGE_TAGS = [
    "beginner", "web", "sqli", "xss", "jwt", "ssrf",
    "crypto", "base64", "xor", "rsa", "aes",
    "pwn", "buffer-overflow", "rop",
    "reversing", "unpacking", "disassembly",
    "forensics", "steganography", "pcap", "metadata",
    "osint", "trivia",
]

# The ~15 challenges, spread across categories/difficulties/tags. ``kind`` selects
# the flag type; the actual answer for static/mc/dynamic lives in
# ``DEMO_SOLUTIONS`` (shared with the simulator). Regex challenges carry their
# pattern here and an example answer in DEMO_SOLUTIONS.
DEMO_CHALLENGES: tuple[dict, ...] = (
    {"title": "Inspect the Source", "category": "Web", "difficulty": "Easy",
     "tags": ["beginner", "web"], "points": 100, "kind": "static",
     "description": "The flag is hiding in plain sight. Open your browser's dev "
                    "tools and read this page's HTML source carefully."},
    {"title": "Little Bobby Tables", "category": "Web", "difficulty": "Medium",
     "tags": ["web", "sqli"], "points": 250, "kind": "static",
     "description": "The login form trusts its input a little too much. Can you "
                    "make the database say more than it should?"},
    {"title": "Reflected", "category": "Web", "difficulty": "Hard",
     "tags": ["web", "xss"], "points": 300, "kind": "regex",
     "regex": r"flag\{xss_[a-z0-9_]+\}",
     "description": "The search box echoes whatever you give it, unescaped. Pop "
                    "an alert — the flag format is flag{xss_...}."},
    {"title": "Base What?", "category": "Crypto", "difficulty": "Easy",
     "tags": ["crypto", "base64"], "points": 150, "kind": "static",
     "description": "ZmxhZ3tiYXNlNjRfaXNfbm90X2VuY3J5cHRpb259 — that's not "
                    "encryption, it's encoding. Decode it."},
    {"title": "Caesar's Secret", "category": "Crypto", "difficulty": "Easy",
     "tags": ["crypto"], "points": 200, "kind": "regex",
     "regex": r"flag\{r0t13_[a-z]+\}",
     "description": "Et tu? Rotate the alphabet by 13 and submit the result as "
                    "flag{r0t13_<word>}."},
    {"title": "XOR-cism", "category": "Crypto", "difficulty": "Medium",
     "tags": ["crypto", "xor"], "points": 300, "kind": "static",
     "description": "A single byte was XOR'd across the whole message. Brute-force "
                    "the key — there are only 256 of them."},
    {"title": "RSA Rookie", "category": "Crypto", "difficulty": "Hard",
     "tags": ["crypto", "rsa"], "points": 450, "kind": "dynamic",
     "min_points": 150, "decay": 20,
     "description": "Someone picked a tiny public exponent and a message with no "
                    "padding. Textbook RSA, textbook mistake."},
    {"title": "Warm Up", "category": "Pwn", "difficulty": "Easy",
     "tags": ["pwn", "beginner"], "points": 500, "kind": "dynamic",
     "min_points": 100, "decay": 20,
     "description": "A gentle introduction to smashing the stack. Worth less as "
                    "more people solve it."},
    {"title": "Ret2Win", "category": "Pwn", "difficulty": "Medium",
     "tags": ["pwn", "buffer-overflow"], "points": 400, "kind": "dynamic",
     "min_points": 150, "decay": 15,
     "description": "There's a win() function that's never called. Overflow the "
                    "buffer and redirect execution to it."},
    {"title": "Strings Attached", "category": "Reversing", "difficulty": "Easy",
     "tags": ["reversing", "beginner"], "points": 150, "kind": "static",
     "description": "Sometimes you don't need a disassembler. Run `strings` on "
                    "the binary and read carefully."},
    {"title": "Packed Lunch", "category": "Reversing", "difficulty": "Medium",
     "tags": ["reversing", "unpacking"], "points": 300, "kind": "static",
     "description": "The binary is compressed with a well-known packer. Unpack it "
                    "first, then look inside."},
    {"title": "Hidden in Plain Sight", "category": "Forensics", "difficulty": "Easy",
     "tags": ["forensics", "steganography", "metadata"], "points": 200, "kind": "static",
     "description": "A perfectly ordinary photo — except the EXIF metadata is "
                    "anything but ordinary."},
    {"title": "Packet Detective", "category": "Forensics", "difficulty": "Medium",
     "tags": ["forensics", "pcap"], "points": 300, "kind": "static",
     "description": "A packet capture of a login over plain HTTP. Follow the TCP "
                    "stream and the flag is in the clear."},
    {"title": "Quick Quiz", "category": "Misc", "difficulty": "Easy",
     "tags": ["trivia", "beginner"], "points": 50, "kind": "mc",
     "choices": ["Capture The Flag", "Command The Fortress",
                 "Code To Function", "Crack The Firewall"],
     "description": "Warm-up trivia: what does CTF stand for?"},
    {"title": "Who Am I?", "category": "OSINT", "difficulty": "Medium",
     "tags": ["osint"], "points": 250, "kind": "static",
     "description": "A single profile photo taken outdoors. Use the reflections "
                    "and the background to work out where it was shot."},
)


def _doc(text: str) -> dict:
    """A minimal TipTap/ProseMirror description doc."""
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _user(display_name: str, email: str) -> User:
    return User(
        display_name=display_name,
        email=email,
        password_hash=hash_password(DEMO_PASSWORD),
    )


def _build_challenge(competition_id: str, category_id: str, spec: dict) -> Challenge:
    """Build a Challenge from a DEMO_CHALLENGES spec. Static/dynamic/MC answers
    come from DEMO_SOLUTIONS (hashed); regex challenges store their pattern."""
    common = dict(
        competition_id=competition_id,
        category_id=category_id,
        title=spec["title"],
        description=_doc(spec["description"]),
        points=spec["points"],
        difficulty=spec["difficulty"],
        tags=list(spec["tags"]),
        state="published",
    )
    kind = spec["kind"]
    if kind == "regex":
        return Challenge(**common, flag_type="regex", flag_regex=spec["regex"])

    salt = make_salt()
    flag_hash = hash_static_flag(DEMO_SOLUTIONS[spec["title"]], salt, False)
    if kind == "mc":
        return Challenge(
            **common, flag_type="multiple_choice", choices=list(spec["choices"]),
            flag_salt=salt, flag_hash=flag_hash,
        )
    extra = {}
    if kind == "dynamic":
        extra = dict(scoring_type="dynamic", min_points=spec["min_points"], decay=spec["decay"])
    return Challenge(**common, flag_type="static", flag_salt=salt, flag_hash=flag_hash, **extra)


async def seed_demo_data(db: AsyncSession) -> None:
    """Seed the demo accounts + sample competition. Idempotent + demo-only."""
    # Idempotency guard: bail if the demo competition already exists (a marker
    # unique to this seed, so it never collides with a real account named "admin").
    if await db.scalar(
        select(Competition.id).where(Competition.name == DEMO_COMPETITION_NAME)
    ):
        return

    roles = {
        r.name: r
        for r in (
            await db.scalars(
                select(Role).where(
                    Role.name.in_(["Administrator", "Judge", "Participant"])
                )
            )
        ).all()
    }
    if not {"Administrator", "Judge", "Participant"} <= roles.keys():
        # System roles seed before this in the lifespan; their absence is a fault.
        return

    # --- Accounts -------------------------------------------------------------
    admin = _user("admin", "admin@demo.flagpost.io")
    judge = _user("judge", "judge@demo.flagpost.io")
    participant = _user("participant", "participant@demo.flagpost.io")
    # Extra solvers so the scoreboard isn't empty (not advertised on login).
    alice = _user("alice", "alice@demo.flagpost.io")
    bob = _user("bob", "bob@demo.flagpost.io")
    db.add_all([admin, judge, participant, alice, bob])
    await db.flush()

    # --- Competition ----------------------------------------------------------
    comp = Competition(
        name=DEMO_COMPETITION_NAME,
        description="A sample competition — explore challenges, the scoreboard, "
                    "support tickets, automations, and more.",
        participation_mode="individual",
        visibility="public",
        public_scoreboard=True,
        challenge_tags=list(DEMO_CHALLENGE_TAGS),
        difficulty_tiers=list(DEMO_DIFFICULTY_TIERS),
        invite_code=generate_invite_code(),
        # The demo is a live competition: start it running so competitors (and the
        # activity simulator) can submit immediately. The #221 status gate defaults
        # new competitions to not_started, which would otherwise block the demo.
        # No schedule, so mark the start boundary handled to keep the scheduler off.
        status="running",
        started_event_fired=True,
    )
    db.add(comp)
    await db.flush()

    # Global admin; competition-scoped judge + participants.
    db.add(RoleAssignment(user_id=admin.id, role_id=roles["Administrator"].id, competition_id=None))
    db.add(RoleAssignment(user_id=judge.id, role_id=roles["Judge"].id, competition_id=comp.id))
    for u in (participant, alice, bob):
        db.add(RoleAssignment(user_id=u.id, role_id=roles["Participant"].id, competition_id=comp.id))

    # --- Categories -----------------------------------------------------------
    cats = {name: Category(competition_id=comp.id, name=name) for name in DEMO_CATEGORIES}
    db.add_all(cats.values())
    await db.flush()

    # --- Challenges (built from DEMO_CHALLENGES) ------------------------------
    challenges: dict[str, Challenge] = {}
    for spec in DEMO_CHALLENGES:
        challenge = _build_challenge(comp.id, cats[spec["category"]].id, spec)
        db.add(challenge)
        challenges[spec["title"]] = challenge
    await db.flush()

    # --- Hints ----------------------------------------------------------------
    db.add(Hint(competition_id=comp.id, challenge_id=challenges["Inspect the Source"].id,
                body="Try right-clicking → View Page Source (or press Ctrl+U).", cost=0))
    db.add(Hint(competition_id=comp.id, challenge_id=challenges["Base What?"].id,
                body="The name is a big hint — it's Base64.", cost=10))
    db.add(Hint(competition_id=comp.id, challenge_id=challenges["RSA Rookie"].id,
                body="A tiny exponent (like e=3) with no padding means you can just take the eth root.", cost=25))

    # --- Automations (the automations module is on by default, §11.3) --------
    # Showcase rules the simulator's traffic will visibly trip:
    #   1) first blood → celebratory announcement + a bonus award (its points
    #      fold into the scoreboard); fires once per challenge via is_first_blood.
    #   2) a new participant joins → a personal welcome notification.
    #   3) any correct solve → a personal "nice solve" notification to the solver.
    db.add_all([
        AutomationRule(
            competition_id=comp.id,
            name="First blood celebration",
            trigger_type="challenge.solved",
            conditions=[{"field": "is_first_blood", "operator": "equals", "value": True}],
            actions=[
                {"type": "create_announcement",
                 # ⚡ matches the lightning-bolt first-blood marker used across
                 # the UI (FirstBloodIcon) — not the old blood-drop idiom (#25).
                 # {user_name}/{challenge_title} showcase the friendly template
                 # fields (#27) — and make successive announcements visibly
                 # distinct, so the banner clearly changes per first blood (#19).
                 "title": "⚡ First blood!",
                 "body": "{user_name} drew first blood on {challenge_title} and earned a bonus. Who's next?"},
                {"type": "create_award",
                 "title": "First Blood",
                 "description": "Awarded for the first solve of a challenge.",
                 "points": 50},
            ],
        ),
        AutomationRule(
            competition_id=comp.id,
            name="Welcome new participants",
            trigger_type="competition.member_joined",
            conditions=[],
            actions=[
                {"type": "notify", "target": "event_user",
                 "title": "Welcome to the Flagpost Demo CTF! 🎉",
                 "body": "Head to Challenges to start solving — good luck!"},
            ],
        ),
        AutomationRule(
            competition_id=comp.id,
            name="Congratulate solvers",
            trigger_type="challenge.solved",
            conditions=[],
            actions=[
                {"type": "notify", "target": "event_user",
                 "title": "Nice solve! 🚩",
                 "body": "You solved {challenge_title} for {points} points. Keep it up!"},
            ],
        ),
    ])

    # --- A few solves so the scoreboard has data (individual mode: team_id None).
    # These are direct rows (not API submissions), so they emit no events — and
    # only a handful of challenges are pre-solved, leaving most for the simulator
    # to claim first blood on (tripping the automation above).
    def _solve(user: User, title: str) -> Submission:
        challenge = challenges[title]
        return Submission(
            competition_id=comp.id, challenge_id=challenge.id, user_id=user.id,
            team_id=None, value="(demo seed)", is_correct=True, is_duplicate=False,
            points_awarded=challenge.points,
        )

    db.add_all([
        _solve(alice, "Inspect the Source"),
        _solve(alice, "Base What?"),
        _solve(alice, "Strings Attached"),
        _solve(participant, "Inspect the Source"),
        _solve(participant, "Quick Quiz"),
        _solve(bob, "Quick Quiz"),
    ])

    # Seeding the owner *is* provisioning, so mark the install complete through
    # the single writer — same as seed_admin_user and the wizard. Without it a
    # fresh demo volume (whose backfill migration ran on an empty DB) boots
    # straight into the setup wizard (#132), and the gate keys on this flag, not
    # admin presence (ADR-0017 / GHSA-ccm4-9573-9965).
    await mark_setup_complete(db)

    await db.commit()
