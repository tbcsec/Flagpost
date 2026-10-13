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


async def _solve(db, comp_id, chal_id, user_id, *, correct=True, duplicate=False, points=100):
    db.add(
        Submission(
            competition_id=comp_id,
            challenge_id=chal_id,
            user_id=user_id,
            value="f",
            is_correct=correct,
            is_duplicate=duplicate,
            points_awarded=points if correct and not duplicate else 0,
        )
    )


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
    assert ada_row["scores"]["web"] == {"weighted": 200, "solved": 2, "available": 2, "pct": 100}
    assert ada_row["scores"]["pwn"] == {"weighted": 100, "solved": 1, "available": 1, "pct": 100}
    bo_row = matrix["users"][1]
    assert bo_row["scores"] == {"web": {"weighted": 100, "solved": 1, "available": 1, "pct": 0}}
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
