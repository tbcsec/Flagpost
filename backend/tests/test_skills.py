"""Cross-competition skills web read model (#364, ADR-0039).

Exercises `utils/skills` directly against seeded rows: the aggregation counts
distinct awarded solves per normalized category name, merges the same category
across competitions (and casing), excludes duplicates / wrong / uncategorized,
and weights each solve by `+1`. The endpoint layer is covered in
`test_skills_api`.
"""

from auth.security import hash_password
from db import SessionLocal
from models.challenge import Category, Challenge
from models.competition import Competition
from models.submission import Submission
from models.user import User
from utils.skills import (
    compute_skill_matrix,
    compute_user_skills,
    normalize_skill,
    solve_weight,
)


async def _competition(db, code: str) -> str:
    comp = Competition(
        name=f"CTF {code}",
        participation_mode="individual",
        visibility="public",
        invite_code=code,
    )
    db.add(comp)
    await db.flush()
    return comp.id


async def _category(db, comp_id: str, name: str) -> str:
    cat = Category(competition_id=comp_id, name=name)
    db.add(cat)
    await db.flush()
    return cat.id


async def _challenge(db, comp_id: str, *, category_id=None, title="C") -> str:
    chal = Challenge(
        competition_id=comp_id,
        title=title,
        description={},
        category_id=category_id,
        points=100,
        state="published",
        flag_hash="x",
        flag_salt="s",
    )
    db.add(chal)
    await db.flush()
    return chal.id


async def _user(db, name: str) -> str:
    user = User(display_name=name, password_hash=hash_password("password123"))
    db.add(user)
    await db.flush()
    return user.id


async def _solve(db, comp_id, chal_id, user_id, *, correct=True, duplicate=False, points=100, at=None):
    sub = Submission(
        competition_id=comp_id,
        challenge_id=chal_id,
        user_id=user_id,
        value="f",
        is_correct=correct,
        is_duplicate=duplicate,
        points_awarded=points if correct and not duplicate else 0,
    )
    if at is not None:
        sub.created_at = at
    db.add(sub)


async def _member(db, comp_id, user_id):
    """A competition-scoped Participant assignment — opportunity, for the
    enriched matrix's `available` denominator (#435)."""
    from sqlalchemy import select

    from models.role import Role, RoleAssignment

    role_id = await db.scalar(select(Role.id).where(Role.name == "Participant"))
    db.add(RoleAssignment(user_id=user_id, role_id=role_id, competition_id=comp_id))


def test_normalize_skill_folds_case_and_whitespace():
    assert normalize_skill("Web") == "web"
    assert normalize_skill("  Web   Exploitation ") == "web exploitation"
    assert normalize_skill("PWN") == normalize_skill("pwn")


def test_solve_weight_is_one_per_box():
    assert solve_weight() == 1


async def test_user_web_counts_distinct_solves_per_category():
    async with SessionLocal() as db:
        comp = await _competition(db, "AAAA0001")
        web = await _category(db, comp, "Web")
        crypto = await _category(db, comp, "Crypto")
        w1 = await _challenge(db, comp, category_id=web, title="w1")
        w2 = await _challenge(db, comp, category_id=web, title="w2")
        c1 = await _challenge(db, comp, category_id=crypto, title="c1")
        user = await _user(db, "ada")
        for chal in (w1, w2, c1):
            await _solve(db, comp, chal, user)
        await db.commit()

        result = await compute_user_skills(db, user)

    scores = {e["skill"]: e["score"] for e in result["skills"]}
    assert scores == {"web": 2, "crypto": 1}
    assert result["total"] == 3
    assert result["competitions_played"] == 1
    # Sorted strongest-axis-first.
    assert [e["skill"] for e in result["skills"]] == ["web", "crypto"]


async def test_web_merges_same_category_across_competitions_case_insensitively():
    async with SessionLocal() as db:
        comp_a = await _competition(db, "AAAA0002")
        comp_b = await _competition(db, "BBBB0002")
        cat_a = await _category(db, comp_a, "Web")  # capitalised in A
        cat_b = await _category(db, comp_b, "web")  # lower-case in B
        a1 = await _challenge(db, comp_a, category_id=cat_a, title="a1")
        b1 = await _challenge(db, comp_b, category_id=cat_b, title="b1")
        b2 = await _challenge(db, comp_b, category_id=cat_b, title="b2")
        user = await _user(db, "bo")
        for comp, chal in ((comp_a, a1), (comp_b, b1), (comp_b, b2)):
            await _solve(db, comp, chal, user)
        await db.commit()

        result = await compute_user_skills(db, user)

    # One merged axis spanning both events, not two separate "Web"/"web" axes.
    assert result["skills"] == [{"skill": "web", "score": 3}]
    assert result["competitions_played"] == 2


async def test_web_excludes_duplicates_wrong_and_uncategorized():
    async with SessionLocal() as db:
        comp = await _competition(db, "AAAA0003")
        web = await _category(db, comp, "Web")
        solved = await _challenge(db, comp, category_id=web, title="solved")
        wrong_only = await _challenge(db, comp, category_id=web, title="wrong")
        uncategorized = await _challenge(db, comp, category_id=None, title="misc")
        user = await _user(db, "cy")
        await _solve(db, comp, solved, user)  # counts
        await _solve(db, comp, solved, user, duplicate=True)  # re-submit: ignored
        await _solve(db, comp, wrong_only, user, correct=False)  # wrong: ignored
        await _solve(db, comp, uncategorized, user)  # no category: ignored
        await db.commit()

        result = await compute_user_skills(db, user)

    assert result["skills"] == [{"skill": "web", "score": 1}]
    assert result["total"] == 1


async def test_empty_web_for_a_user_with_no_solves():
    async with SessionLocal() as db:
        user = await _user(db, "newbie")
        await db.commit()
        result = await compute_user_skills(db, user)
    assert result == {"skills": [], "total": 0, "competitions_played": 0}


async def test_matrix_lists_users_by_total_with_a_shared_axis():
    async with SessionLocal() as db:
        comp = await _competition(db, "AAAA0004")
        web = await _category(db, comp, "Web")
        pwn = await _category(db, comp, "Pwn")
        w1 = await _challenge(db, comp, category_id=web, title="w1")
        w2 = await _challenge(db, comp, category_id=web, title="w2")
        p1 = await _challenge(db, comp, category_id=pwn, title="p1")
        ada = await _user(db, "ada")
        bo = await _user(db, "bo")
        # ada: 2 web + 1 pwn = 3; bo: 1 web = 1.
        for chal in (w1, w2, p1):
            await _solve(db, comp, chal, ada)
        await _solve(db, comp, w1, bo)
        await db.commit()

        matrix = await compute_skill_matrix(db)

    # Shared, sorted axis (columns) across all users.
    assert matrix["skills"] == ["pwn", "web"]
    # Users ranked by total weighted descending.
    assert [u["display_name"] for u in matrix["users"]] == ["ada", "bo"]
    ada_row = matrix["users"][0]
    assert ada_row["total"] == 3
    assert ada_row["total_weighted"] == 300
    # Enriched cells (#435): weighted points, coverage (no memberships here, so
    # `available` clamps to solved), and the column percentile.
    # v2 signals ride along: ada's 2 web submissions were both solves (clean),
    # and she drew first blood on both web challenges (bo solved w1 later).
    assert ada_row["scores"]["web"] == {
        "weighted": 200, "solved": 2, "available": 2, "pct": 100,
        "attempts": 2, "hints": 0, "first_bloods": 2,
    }
    assert ada_row["scores"]["pwn"] == {
        "weighted": 100, "solved": 1, "available": 1, "pct": 100,
        "attempts": 1, "hints": 0, "first_bloods": 1,
    }
    bo_row = matrix["users"][1]
    assert bo_row["scores"] == {
        "web": {
            "weighted": 100, "solved": 1, "available": 1, "pct": 0,
            "attempts": 1, "hints": 0, "first_bloods": 0,
        }
    }
    # The population footer: solvers + mean weighted per column.
    assert matrix["population"] == {
        "pwn": {"solvers": 1, "mean_weighted": 100},
        "web": {"solvers": 2, "mean_weighted": 150},
    }


async def test_availability_counts_published_challenges_in_member_competitions():
    async with SessionLocal() as db:
        comp = await _competition(db, "AAAA0006")
        web = await _category(db, comp, "Web")
        w = [await _challenge(db, comp, category_id=web, title=f"w{i}") for i in range(3)]
        # A draft is not opportunity — it must not inflate `available`.
        db.add(
            Challenge(
                competition_id=comp, title="draft", description={}, category_id=web,
                points=100, state="draft", flag_hash="x", flag_salt="s",
            )
        )
        ada = await _user(db, "ada-avail")
        bo = await _user(db, "bo-avail")
        await _member(db, comp, ada)  # ada is a member; bo never joined
        await _solve(db, comp, w[0], ada)
        await _solve(db, comp, w[0], bo)
        await db.commit()

        matrix = await compute_skill_matrix(db)

    rows = {u["display_name"]: u for u in matrix["users"]}
    # Member: 3 published challenges of opportunity (the draft excluded).
    assert rows["ada-avail"]["scores"]["web"]["available"] == 3
    assert rows["ada-avail"]["scores"]["web"]["solved"] == 1
    # Non-member: no opportunity rows, so `available` clamps to solved — never "1/0".
    assert rows["bo-avail"]["scores"]["web"]["available"] == 1


async def test_percentile_is_the_cross_scale_comparator():
    """Points don't normalize across competitions (the ADR-0039 caveat): one
    1000-point solve out-weighs three 100-point solves. The percentile column is
    where the comparison is honest — both facts are served, labeled."""
    async with SessionLocal() as db:
        comp_a = await _competition(db, "AAAA0007")
        comp_b = await _competition(db, "AAAA0008")
        web_a = await _category(db, comp_a, "Web")
        web_b = await _category(db, comp_b, "Web")
        small = [await _challenge(db, comp_a, category_id=web_a, title=f"s{i}") for i in range(3)]
        big = await _challenge(db, comp_b, category_id=web_b, title="big")
        dana = await _user(db, "dana")
        charlie = await _user(db, "charlie")
        for chal in small:
            await _solve(db, comp_a, chal, dana, points=100)
        await _solve(db, comp_b, big, charlie, points=1000)
        await db.commit()

        matrix = await compute_skill_matrix(db)

    rows = {u["display_name"]: u for u in matrix["users"]}
    # Raw weighted carries the scale distortion…
    assert rows["charlie"]["scores"]["web"]["weighted"] == 1000
    assert rows["dana"]["scores"]["web"]["weighted"] == 300
    # …and the solved count + percentile are the per-axis correctives.
    assert rows["dana"]["scores"]["web"]["solved"] == 3
    assert rows["charlie"]["scores"]["web"]["pct"] == 100
    assert rows["dana"]["scores"]["web"]["pct"] == 0


async def test_window_bounds_activity_but_not_the_first_blood_fact():
    """#440: a window filters which activity counts, but first blood is a
    historical fact — the second solver is never crowned just because the true
    first scrolled out of the window."""
    from datetime import timedelta

    from db import utcnow

    async with SessionLocal() as db:
        comp = await _competition(db, "AAAA0009")
        web = await _category(db, comp, "Web")
        w1 = await _challenge(db, comp, category_id=web, title="w1")
        old = await _user(db, "old-timer")
        new = await _user(db, "newcomer")
        # old-timer drew first blood 200 days ago; newcomer solved yesterday.
        await _solve(db, comp, w1, old, at=utcnow() - timedelta(days=200))
        await _solve(db, comp, w1, new, at=utcnow() - timedelta(days=1))
        await db.commit()

        everything = await compute_skill_matrix(db, "all")
        recent = await compute_skill_matrix(db, "90")

    rows_all = {u["display_name"]: u for u in everything["users"]}
    assert rows_all["old-timer"]["scores"]["web"]["first_bloods"] == 1
    assert rows_all["newcomer"]["scores"]["web"]["first_bloods"] == 0

    rows_recent = {u["display_name"]: u for u in recent["users"]}
    # The old solve (and its first blood) fall outside the window entirely…
    assert "old-timer" not in rows_recent
    # …and the newcomer is NOT promoted to first blood: the fact is all-time.
    assert rows_recent["newcomer"]["scores"]["web"]["first_bloods"] == 0
    assert rows_recent["newcomer"]["scores"]["web"]["solved"] == 1


async def test_attempts_and_hints_count_into_cells():
    """#440 efficiency signals: wrong guesses and hint reveals accumulate on the
    cell (attempts include struggle on a never-solved challenge in the same
    category — that's signal, not noise)."""
    from models.hint import Hint, HintReveal

    async with SessionLocal() as db:
        comp = await _competition(db, "AAAA0010")
        web = await _category(db, comp, "Web")
        w1 = await _challenge(db, comp, category_id=web, title="w1")
        w2 = await _challenge(db, comp, category_id=web, title="w2")
        user = await _user(db, "grinder")
        # Two wrong guesses on w1, then the solve; one wrong guess on w2, never
        # solved. A duplicate re-submit must not count as an attempt.
        await _solve(db, comp, w1, user, correct=False)
        await _solve(db, comp, w1, user, correct=False)
        await _solve(db, comp, w1, user)
        await _solve(db, comp, w1, user, duplicate=True)
        await _solve(db, comp, w2, user, correct=False)
        hint = Hint(competition_id=comp, challenge_id=w1, body="look closer", cost=0)
        db.add(hint)
        await db.flush()
        db.add(
            HintReveal(
                competition_id=comp, hint_id=hint.id, challenge_id=w1,
                user_id=user, cost_charged=0,
            )
        )
        await db.commit()

        matrix = await compute_skill_matrix(db)

    cell = {u["display_name"]: u for u in matrix["users"]}["grinder"]["scores"]["web"]
    assert cell["solved"] == 1
    assert cell["attempts"] == 4  # 3 on w1 (dup excluded) + 1 on w2
    assert cell["hints"] == 1


async def test_user_skill_detail_shape():
    """The drill-down (#440): per-skill rollups + solve rows with context."""
    from utils.skills import compute_user_skill_detail

    async with SessionLocal() as db:
        comp = await _competition(db, "AAAA0011")
        web = await _category(db, comp, "Web")
        w1 = await _challenge(db, comp, category_id=web, title="Heist")
        user = await _user(db, "sleuth")
        await _solve(db, comp, w1, user, correct=False)
        await _solve(db, comp, w1, user, points=250)
        await db.commit()

        detail = await compute_user_skill_detail(db, user)
        missing = await compute_user_skill_detail(db, "not-a-user")

    assert missing is None
    assert detail["display_name"] == "sleuth"
    assert detail["total"] == 1 and detail["total_weighted"] == 250
    assert detail["skills"] == [
        {"skill": "web", "weighted": 250, "solved": 1, "attempts": 2, "hints": 0, "first_bloods": 1}
    ]
    [solve] = detail["solves"]
    assert solve["challenge_title"] == "Heist"
    assert solve["skill"] == "web"
    assert solve["points_awarded"] == 250
    assert solve["attempts"] == 2
    assert solve["first_blood"] is True
