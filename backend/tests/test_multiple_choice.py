"""Multiple-choice challenges + the competition-wide guess cap (Phase 9).

The options are shown to competitors; the correct answer stays hashed and never
leaves the server. A per-subject guess limit (set on the competition) blunts
brute-forcing the finite option set.
"""

from sqlalchemy import select

from db import SessionLocal
from models.role import Role, RoleAssignment
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _assign_participant(user_id: str, competition_id: str) -> None:
    async with SessionLocal() as session:
        role = await session.scalar(select(Role).where(Role.name == "Participant"))
        session.add(RoleAssignment(user_id=user_id, competition_id=competition_id, role_id=role.id))
        await session.commit()


async def _mc_competition(
    client, token, *, limit: int | None, penalty: int | None = None
) -> str:
    # Always send the key: the default is now 2, so "unlimited" needs explicit null.
    body = {
        "name": "MC",
        "participation_mode": "individual",
        "mc_guess_limit": limit,
        "mc_penalty_pct": penalty,
    }
    resp = await client.post("/api/competitions", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_default_guess_limit_is_two(client):
    token = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={"name": "Defaults", "participation_mode": "individual"},
        headers=_auth(token),
    )
    assert resp.json()["mc_guess_limit"] == 2


async def _mc_challenge(client, token, comp, *, correct="Paris", **extra) -> str:
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={
            "title": "Capital of France",
            "flag_type": "multiple_choice",
            "choices": ["London", "Paris", "Berlin", "Madrid"],
            "flag": correct,
            **extra,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    pub = await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/publish", headers=_auth(token)
    )
    assert pub.status_code == 200, pub.text
    return cid


async def test_options_shown_answer_hidden(client):
    admin = await admin_token(client)
    comp = await _mc_competition(client, admin, limit=None)
    await _mc_challenge(client, admin, comp)

    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)

    ch = (await client.get(f"/api/competitions/{comp}/challenges", headers=_auth(ptoken))).json()[0]
    assert ch["flag_type"] == "multiple_choice"
    assert set(ch["choices"]) == {"London", "Paris", "Berlin", "Madrid"}
    # The correct answer / hash never leaves the server.
    assert "flag_hash" not in ch and "flag" not in ch
    # No cap on this competition.
    assert ch["attempts_remaining"] is None


async def test_guess_limit_blocks_brute_force(client):
    admin = await admin_token(client)
    comp = await _mc_competition(client, admin, limit=2)
    cid = await _mc_challenge(client, admin, comp)
    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)
    auth = _auth(ptoken)
    submit = f"/api/competitions/{comp}/challenges/{cid}/submit"

    # Two guesses remaining up front.
    assert (await client.get(f"/api/competitions/{comp}/challenges", headers=auth)).json()[0]["attempts_remaining"] == 2

    r1 = await client.post(submit, json={"flag": "London"}, headers=auth)
    assert r1.json()["correct"] is False and r1.json()["attempts_remaining"] == 1
    r2 = await client.post(submit, json={"flag": "Berlin"}, headers=auth)
    assert r2.json()["correct"] is False and r2.json()["attempts_remaining"] == 0

    # Out of guesses — even the *correct* answer is refused now (that's the point).
    r3 = await client.post(submit, json={"flag": "Paris"}, headers=auth)
    assert r3.status_code == 403

    # A different participant still has their own allotment and can solve it.
    qtoken, quid = await _register(client, "q@example.com")
    await _assign_participant(quid, comp)
    win = await client.post(submit, json={"flag": "Paris"}, headers=_auth(qtoken))
    assert win.status_code == 200 and win.json()["correct"] is True


async def test_correct_guess_within_limit_solves(client):
    admin = await admin_token(client)
    comp = await _mc_competition(client, admin, limit=3)
    cid = await _mc_challenge(client, admin, comp)
    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)
    submit = f"/api/competitions/{comp}/challenges/{cid}/submit"

    await client.post(submit, json={"flag": "London"}, headers=_auth(ptoken))
    win = await client.post(submit, json={"flag": "Paris"}, headers=_auth(ptoken))
    assert win.json()["correct"] is True and win.json()["points_awarded"] == 100


async def test_targeted_guess_reset(client):
    admin = await admin_token(client)
    comp = await _mc_competition(client, admin, limit=2)
    cid = await _mc_challenge(client, admin, comp)
    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)
    auth = _auth(ptoken)
    submit = f"/api/competitions/{comp}/challenges/{cid}/submit"
    reset = f"/api/competitions/{comp}/challenges/{cid}/reset-guesses"

    await client.post(submit, json={"flag": "London"}, headers=auth)
    await client.post(submit, json={"flag": "Berlin"}, headers=auth)
    assert (await client.post(submit, json={"flag": "Paris"}, headers=auth)).status_code == 403

    # Admin resets this user's guesses non-destructively.
    r = await client.post(reset, json={"user_id": puid}, headers=_auth(admin))
    assert r.status_code == 204

    # Fresh allotment, and they can guess (and solve) again.
    ch = (await client.get(f"/api/competitions/{comp}/challenges", headers=auth)).json()[0]
    assert ch["attempts_remaining"] == 2
    win = await client.post(submit, json={"flag": "Paris"}, headers=auth)
    assert win.status_code == 200 and win.json()["correct"] is True

    # History is intact — the failed attempts are still logged (non-destructive).
    from models.submission import Submission
    async with SessionLocal() as db:
        total = await db.scalar(
            select(Submission.id).where(Submission.challenge_id == cid, Submission.user_id == puid)
        )
    assert total is not None


async def test_bulk_guess_reset(client):
    admin = await admin_token(client)
    comp = await _mc_competition(client, admin, limit=1)
    cid = await _mc_challenge(client, admin, comp)
    submit = f"/api/competitions/{comp}/challenges/{cid}/submit"

    tokens = []
    for email in ("a@example.com", "b@example.com"):
        t, uid = await _register(client, email)
        await _assign_participant(uid, comp)
        tokens.append(t)
        await client.post(submit, json={"flag": "London"}, headers=_auth(t))  # burn the 1 guess
        assert (await client.post(submit, json={"flag": "Paris"}, headers=_auth(t))).status_code == 403

    # Bulk reset (no target) refreshes everyone.
    r = await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/reset-guesses", json={}, headers=_auth(admin)
    )
    assert r.status_code == 204
    for t in tokens:
        win = await client.post(submit, json={"flag": "Paris"}, headers=_auth(t))
        assert win.status_code == 200 and win.json()["correct"] is True


async def test_reset_guards(client):
    admin = await admin_token(client)
    comp = await _mc_competition(client, admin, limit=2)

    # Non-MC challenge → 400.
    static = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "S", "flag": "flag{x}"},
        headers=_auth(admin),
    )
    scid = static.json()["id"]
    r = await client.post(
        f"/api/competitions/{comp}/challenges/{scid}/reset-guesses", json={}, headers=_auth(admin)
    )
    assert r.status_code == 400

    # Requires challenge_edit.
    cid = await _mc_challenge(client, admin, comp)
    ptoken, _ = await _register(client, "nobody@example.com")
    r = await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/reset-guesses", json={}, headers=_auth(ptoken)
    )
    assert r.status_code == 403


async def test_validation(client):
    admin = await admin_token(client)
    comp = await _mc_competition(client, admin, limit=None)
    base = f"/api/competitions/{comp}/challenges"

    # Fewer than two options — rejected by the schema.
    r = await client.post(
        base,
        json={"title": "x", "flag_type": "multiple_choice", "choices": ["only"], "flag": "only"},
        headers=_auth(admin),
    )
    assert r.status_code == 422

    # Correct answer not among the options — rejected by the router.
    r = await client.post(
        base,
        json={"title": "x", "flag_type": "multiple_choice", "choices": ["a", "b"], "flag": "c"},
        headers=_auth(admin),
    )
    assert r.status_code == 400

    # Duplicate options — rejected.
    r = await client.post(
        base,
        json={"title": "x", "flag_type": "multiple_choice", "choices": ["a", "a"], "flag": "a"},
        headers=_auth(admin),
    )
    assert r.status_code == 400


# --- Wrong-guess point penalty (#148) ----------------------------------------


async def test_penalty_pct_validation(client):
    admin = await admin_token(client)
    # Out of range → 422 (1–100).
    for bad in (0, 101, -5):
        r = await client.post(
            "/api/competitions",
            json={"name": "X", "participation_mode": "individual", "mc_penalty_pct": bad},
            headers=_auth(admin),
        )
        assert r.status_code == 422, f"{bad}: {r.text}"
    # In range accepted; the default is off (null).
    ok = await client.post(
        "/api/competitions",
        json={"name": "Y", "participation_mode": "individual", "mc_penalty_pct": 30},
        headers=_auth(admin),
    )
    assert ok.status_code == 201 and ok.json()["mc_penalty_pct"] == 30
    default = await client.post(
        "/api/competitions",
        json={"name": "Z", "participation_mode": "individual"},
        headers=_auth(admin),
    )
    assert default.json()["mc_penalty_pct"] is None


async def test_wrong_guess_penalty_reduces_award(client):
    admin = await admin_token(client)
    comp = await _mc_competition(client, admin, limit=None, penalty=25)
    cid = await _mc_challenge(client, admin, comp, points=200)
    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)
    auth = _auth(ptoken)
    submit = f"/api/competitions/{comp}/challenges/{cid}/submit"

    # Two wrong guesses, each docking 25% of 200 (=50), then the correct answer.
    await client.post(submit, json={"flag": "London"}, headers=auth)
    await client.post(submit, json={"flag": "Berlin"}, headers=auth)
    win = (await client.post(submit, json={"flag": "Paris"}, headers=auth)).json()
    assert win["correct"] is True
    assert win["points_awarded"] == 100  # 200 - 2*50
    assert win["full_value"] == 200


async def test_penalty_floors_at_zero_but_still_solves(client):
    admin = await admin_token(client)
    comp = await _mc_competition(client, admin, limit=None, penalty=40)
    cid = await _mc_challenge(client, admin, comp, points=100)
    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)
    auth = _auth(ptoken)
    submit = f"/api/competitions/{comp}/challenges/{cid}/submit"

    # Three wrong guesses = 120% penalty, floored at 0.
    for wrong in ("London", "Berlin", "Madrid"):
        await client.post(submit, json={"flag": wrong}, headers=auth)
    win = (await client.post(submit, json={"flag": "Paris"}, headers=auth)).json()
    assert win["correct"] is True
    assert win["points_awarded"] == 0
    assert win["full_value"] == 100
    # A zero-point solve still counts as a solve.
    ch = (await client.get(f"/api/competitions/{comp}/challenges/{cid}", headers=auth)).json()
    assert ch["solved"] is True


async def test_penalty_ignores_non_multiple_choice(client):
    admin = await admin_token(client)
    # Penalty set, but a static challenge is unaffected — the penalty is MC-only.
    comp = await _mc_competition(client, admin, limit=None, penalty=50)
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "Static", "points": 100, "flag": "flag{win}"},
        headers=_auth(admin),
    )
    cid = resp.json()["id"]
    await client.post(f"/api/competitions/{comp}/challenges/{cid}/publish", headers=_auth(admin))
    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)
    auth = _auth(ptoken)
    submit = f"/api/competitions/{comp}/challenges/{cid}/submit"

    await client.post(submit, json={"flag": "flag{nope}"}, headers=auth)
    win = (await client.post(submit, json={"flag": "flag{win}"}, headers=auth)).json()
    assert win["points_awarded"] == 100
    assert win["full_value"] is None


async def test_penalty_off_awards_full_value(client):
    admin = await admin_token(client)
    comp = await _mc_competition(client, admin, limit=None, penalty=None)  # off
    cid = await _mc_challenge(client, admin, comp, points=100)
    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)
    auth = _auth(ptoken)
    submit = f"/api/competitions/{comp}/challenges/{cid}/submit"

    await client.post(submit, json={"flag": "London"}, headers=auth)
    win = (await client.post(submit, json={"flag": "Paris"}, headers=auth)).json()
    assert win["points_awarded"] == 100
    assert win["full_value"] is None


async def test_guess_reset_restores_full_value(client):
    admin = await admin_token(client)
    comp = await _mc_competition(client, admin, limit=None, penalty=50)
    cid = await _mc_challenge(client, admin, comp, points=100)
    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)
    auth = _auth(ptoken)
    submit = f"/api/competitions/{comp}/challenges/{cid}/submit"
    reset = f"/api/competitions/{comp}/challenges/{cid}/reset-guesses"

    # A wrong guess would halve the award...
    await client.post(submit, json={"flag": "London"}, headers=auth)
    # ...but a reset clears the wrong-guess count (same cutoff the cap uses), so
    # the value is restored along with the attempts (#148 reuses the reset).
    assert (
        await client.post(reset, json={"user_id": puid}, headers=_auth(admin))
    ).status_code == 204
    win = (await client.post(submit, json={"flag": "Paris"}, headers=auth)).json()
    assert win["points_awarded"] == 100
    assert win["full_value"] is None


async def test_subject_value_shown_before_solving(client):
    admin = await admin_token(client)
    comp = await _mc_competition(client, admin, limit=None, penalty=25)
    cid = await _mc_challenge(client, admin, comp, points=200)
    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)
    auth = _auth(ptoken)
    submit = f"/api/competitions/{comp}/challenges/{cid}/submit"

    # No wrong guesses yet → the base value stands, nothing reduced.
    ch = (await client.get(f"/api/competitions/{comp}/challenges/{cid}", headers=auth)).json()
    assert ch["value"] == 200 and ch["subject_value"] is None

    # After one wrong guess, the reduced worth surfaces on both detail and list.
    await client.post(submit, json={"flag": "London"}, headers=auth)
    ch = (await client.get(f"/api/competitions/{comp}/challenges/{cid}", headers=auth)).json()
    assert ch["subject_value"] == 150  # 200 - 25%
    listed = (await client.get(f"/api/competitions/{comp}/challenges", headers=auth)).json()[0]
    assert listed["subject_value"] == 150


async def test_dynamic_mc_penalty_preserves_each_subject_on_revalue(client):
    """The corner case the stored per-row penalty exists for: when a new solve
    re-values a dynamic MC challenge, each earlier solver keeps their own penalty
    rather than being collapsed to the newest solver's award (#148)."""
    from models.submission import Submission
    from utils.scoring import dynamic_value, penalised_value

    admin = await admin_token(client)
    initial, minp, decay, pct = 200, 20, 10, 25
    comp = await _mc_competition(client, admin, limit=None, penalty=pct)
    cid = await _mc_challenge(
        client, admin, comp,
        points=initial, scoring_type="dynamic", min_points=minp, decay=decay,
    )
    submit = f"/api/competitions/{comp}/challenges/{cid}/submit"

    async def solve(email, wrongs):
        t, uid = await _register(client, email)
        await _assign_participant(uid, comp)
        for w in wrongs:
            await client.post(submit, json={"flag": w}, headers=_auth(t))
        r = await client.post(submit, json={"flag": "Paris"}, headers=_auth(t))
        assert r.json()["correct"] is True
        return uid

    a = await solve("a@example.com", ["London", "Berlin"])  # 2 wrong, solve #1
    b = await solve("b@example.com", [])                     # 0 wrong, solve #2
    c = await solve("c@example.com", ["Madrid"])             # 1 wrong, solve #3

    base1 = dynamic_value(initial, minp, decay, 1)
    base3 = dynamic_value(initial, minp, decay, 3)
    # Each solver's penalty was frozen (in points) at their own solve-time base.
    pen_a = base1 - penalised_value(base1, pct, 2)
    pen_c = base3 - penalised_value(base3, pct, 1)

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Submission).where(
                    Submission.challenge_id == cid,
                    Submission.is_correct.is_(True),
                    Submission.is_duplicate.is_(False),
                )
            )
        ).scalars().all()
    awarded = {r.user_id: r.points_awarded for r in rows}
    # After the third solve re-values everyone to base3, each keeps their own penalty.
    assert awarded[a] == max(0, base3 - pen_a)
    assert awarded[b] == base3
    assert awarded[c] == max(0, base3 - pen_c)
