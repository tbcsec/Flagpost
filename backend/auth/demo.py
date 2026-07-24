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

from auth.security import hash_password
from models.challenge import Category, Challenge
from models.competition import Competition, generate_invite_code
from models.hint import Hint
from models.role import Role, RoleAssignment
from models.submission import Submission
from models.user import User
from utils.flags import hash_static_flag, make_salt

DEMO_PASSWORD = "password"
DEMO_COMPETITION_NAME = "Flagpost Demo CTF"


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


def _static_challenge(
    competition_id: str, category_id: str, title: str, description: str,
    flag: str, points: int, state: str = "published",
) -> Challenge:
    salt = make_salt()
    return Challenge(
        competition_id=competition_id,
        category_id=category_id,
        title=title,
        description=_doc(description),
        points=points,
        flag_type="static",
        flag_salt=salt,
        flag_hash=hash_static_flag(flag, salt, False),
        state=state,
    )


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
        description="A sample competition — explore challenges, the scoreboard, and more.",
        participation_mode="individual",
        visibility="public",
        public_scoreboard=True,
        invite_code=generate_invite_code(),
    )
    db.add(comp)
    await db.flush()

    # Global admin; competition-scoped judge + participants.
    db.add(RoleAssignment(user_id=admin.id, role_id=roles["Administrator"].id, competition_id=None))
    db.add(RoleAssignment(user_id=judge.id, role_id=roles["Judge"].id, competition_id=comp.id))
    for u in (participant, alice, bob):
        db.add(RoleAssignment(user_id=u.id, role_id=roles["Participant"].id, competition_id=comp.id))

    # --- Categories + challenges ---------------------------------------------
    cats = {name: Category(competition_id=comp.id, name=name) for name in ("Web", "Crypto", "Misc", "Pwn")}
    db.add_all(cats.values())
    await db.flush()

    inspect = _static_challenge(
        comp.id, cats["Web"].id, "Inspect the Source",
        "Sometimes the flag is hiding in plain sight. Take a closer look at this page.",
        "flag{view_source_hero}", 100,
    )
    base = _static_challenge(
        comp.id, cats["Crypto"].id, "Base What?",
        "ZmxhZ3tiYXNlNjRfaXNfbm90X2VuY3J5cHRpb259 — decode me.",
        "flag{base64_is_not_encryption}", 150,
    )
    # A regex challenge (any rot13 flag matches).
    caesar = Challenge(
        competition_id=comp.id, category_id=cats["Crypto"].id, title="Caesar's Secret",
        description=_doc("Rotate the alphabet and submit flag{r0t13_<word>}."),
        points=200, flag_type="regex", flag_regex=r"flag\{r0t13_[a-z]+\}", state="published",
    )
    # A multiple-choice challenge.
    quiz = Challenge(
        competition_id=comp.id, category_id=cats["Misc"].id, title="Quick Quiz",
        description=_doc("What does CTF stand for?"),
        points=50, flag_type="multiple_choice",
        choices=["Capture The Flag", "Command The Fortress", "Code To Function", "Crack The Firewall"],
        state="published",
    )
    quiz_salt = make_salt()
    quiz.flag_salt = quiz_salt
    quiz.flag_hash = hash_static_flag("Capture The Flag", quiz_salt, False)
    # A dynamic (decay) challenge.
    warmup = Challenge(
        competition_id=comp.id, category_id=cats["Pwn"].id, title="Warm Up",
        description=_doc("A gentle introduction. Worth less as more people solve it."),
        points=500, scoring_type="dynamic", min_points=100, decay=20,
        flag_type="static", state="published",
    )
    warmup_salt = make_salt()
    warmup.flag_salt = warmup_salt
    warmup.flag_hash = hash_static_flag("flag{stack_smashing_101}", warmup_salt, False)

    db.add_all([inspect, base, caesar, quiz, warmup])
    await db.flush()

    db.add(Hint(competition_id=comp.id, challenge_id=inspect.id, body="Try right-clicking → View Page Source.", cost=0))
    db.add(Hint(competition_id=comp.id, challenge_id=base.id, body="The name is a big hint — it's Base64.", cost=10))

    # --- A few solves so the scoreboard has data (individual mode: team_id None) --
    def _solve(user: User, challenge: Challenge, points: int) -> Submission:
        return Submission(
            competition_id=comp.id, challenge_id=challenge.id, user_id=user.id,
            team_id=None, value="(demo seed)", is_correct=True, is_duplicate=False,
            points_awarded=points,
        )

    db.add_all([
        _solve(alice, inspect, 100),
        _solve(alice, base, 150),
        _solve(participant, inspect, 100),
        _solve(bob, quiz, 50),
    ])

    await db.commit()
