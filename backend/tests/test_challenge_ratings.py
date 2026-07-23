"""Challenge ratings (Phase 9, feedback-module extension): only solvers rate, the
per-competition toggle gates it, re-rating updates, and staff read aggregates."""

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
    async with SessionLocal() as db:
        role = await db.scalar(select(Role).where(Role.name == "Participant"))
        db.add(RoleAssignment(user_id=user_id, competition_id=competition_id, role_id=role.id))
        await db.commit()


async def _competition(client, token, *, ratings: bool) -> str:
    resp = await client.post(
        "/api/competitions",
        json={
            "name": "Rated CTF",
            "participation_mode": "individual",
            "challenge_ratings_enabled": ratings,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _published_challenge(client, token, comp, flag="flag{win}") -> str:
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "C", "flag": flag},
        headers=_auth(token),
    )
    cid = resp.json()["id"]
    await client.post(f"/api/competitions/{comp}/challenges/{cid}/publish", headers=_auth(token))
    return cid


async def test_rate_after_solving_and_summary(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin, ratings=True)
    cid = await _published_challenge(client, admin, comp)
    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)
    auth = _auth(ptoken)
    rate = f"/api/competitions/{comp}/challenge-ratings/{cid}"

    # Can't rate before solving.
    assert (await client.post(rate, json={"rating": 5}, headers=auth)).status_code == 403

    await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/submit", json={"flag": "flag{win}"}, headers=auth
    )
    assert (await client.post(rate, json={"rating": 4}, headers=auth)).status_code == 204

    # my_rating surfaces on the challenge read; re-rating updates it.
    ch = (await client.get(f"/api/competitions/{comp}/challenges", headers=auth)).json()[0]
    assert ch["my_rating"] == 4
    await client.post(rate, json={"rating": 2}, headers=auth)
    ch = (await client.get(f"/api/competitions/{comp}/challenges", headers=auth)).json()[0]
    assert ch["my_rating"] == 2  # one rating, updated — not two

    # Staff aggregate.
    summary = (await client.get(f"/api/competitions/{comp}/challenge-ratings", headers=_auth(admin))).json()
    assert len(summary) == 1
    assert summary[0]["count"] == 1 and summary[0]["average"] == 2.0
    assert summary[0]["challenge_id"] == cid


async def test_rating_out_of_range_rejected(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin, ratings=True)
    cid = await _published_challenge(client, admin, comp)
    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)
    auth = _auth(ptoken)
    await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/submit", json={"flag": "flag{win}"}, headers=auth
    )
    for bad in (0, 6, -1):
        r = await client.post(
            f"/api/competitions/{comp}/challenge-ratings/{cid}", json={"rating": bad}, headers=auth
        )
        assert r.status_code == 422


async def test_ratings_toggle_off(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin, ratings=False)
    cid = await _published_challenge(client, admin, comp)
    ptoken, puid = await _register(client, "p@example.com")
    await _assign_participant(puid, comp)
    auth = _auth(ptoken)
    await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/submit", json={"flag": "flag{win}"}, headers=auth
    )
    # Rating refused while the flag is off, and my_rating stays null.
    r = await client.post(
        f"/api/competitions/{comp}/challenge-ratings/{cid}", json={"rating": 5}, headers=auth
    )
    assert r.status_code == 403
    ch = (await client.get(f"/api/competitions/{comp}/challenges", headers=auth)).json()[0]
    assert ch["my_rating"] is None
