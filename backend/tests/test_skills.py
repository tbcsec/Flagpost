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


async def _solve(db, comp_id, chal_id, user_id, *, correct=True, duplicate=False):
    db.add(
        Submission(
            competition_id=comp_id,
            challenge_id=chal_id,
            user_id=user_id,
            value="f",
            is_correct=correct,
            is_duplicate=duplicate,
            points_awarded=100 if correct and not duplicate else 0,
        )
    )


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
    # Users ranked by total descending.
    assert [u["display_name"] for u in matrix["users"]] == ["ada", "bo"]
    ada_row = matrix["users"][0]
    assert ada_row["total"] == 3
    assert ada_row["scores"] == {"web": 2, "pwn": 1}
    assert matrix["users"][1]["scores"] == {"web": 1}
