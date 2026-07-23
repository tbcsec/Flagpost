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


async def _mc_competition(client, token, *, limit: int | None) -> str:
    # Always send the key: the default is now 2, so "unlimited" needs explicit null.
    body = {"name": "MC", "participation_mode": "individual", "mc_guess_limit": limit}
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


async def _mc_challenge(client, token, comp, *, correct="Paris") -> str:
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={
            "title": "Capital of France",
            "flag_type": "multiple_choice",
            "choices": ["London", "Paris", "Berlin", "Madrid"],
            "flag": correct,
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
