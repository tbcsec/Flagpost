"""Site-admin overview (Phase 9): cross-competition totals + per-competition
health, gated on view_global_analytics (Administrator-only)."""

import pytest

from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def _competition(client, admin, mode="individual", **over) -> str:
    body = {"name": "CTF", "participation_mode": mode, "visibility": "public", **over}
    return (await client.post("/api/competitions", json=body, headers=_auth(admin))).json()["id"]


async def _published_challenge(client, admin, comp, flag="flag{a}") -> str:
    cid = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Chal", "points": 100, "flag": flag},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/publish", headers=_auth(admin)
    )
    return cid


async def test_overview_totals_and_health(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    chal = await _published_challenge(client, admin, comp)
    player = await _register(client, "ada@example.com")
    await client.post(f"/api/competitions/{comp}/join", headers=_auth(player))
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{a}"},
        headers=_auth(player),
    )
    # An open ticket.
    await client.post(
        f"/api/competitions/{comp}/tickets",
        json={"subject": "help", "body": "stuck", "challenge_id": chal},
        headers=_auth(player),
    )

    overview = (await client.get("/api/admin/overview", headers=_auth(admin))).json()
    assert overview["total_competitions"] == 1
    assert overview["active_competitions"] == 1
    assert overview["published_challenges"] == 1
    assert overview["total_solves"] == 1
    # ada + the seeded admin.
    assert overview["total_users"] >= 2

    (health,) = overview["competitions"]
    # Running: gameplay happened, so the competition was started (#221).
    assert health["status"] == "running"
    assert health["participants"] == 1  # one individual competitor
    assert health["published_challenges"] == 1
    assert health["solves"] == 1
    assert health["open_tickets"] == 1


@pytest.mark.competition_lifecycle
async def test_overview_status_and_archived(client):
    # Drive statuses explicitly (opt out of the default-running fixture): the
    # overview label now derives from the competition's status (#221), with a
    # future start_at distinguishing "scheduled" from a "draft".
    admin = await admin_token(client)
    running = await _competition(client, admin)
    await client.post(f"/api/competitions/{running}/start", headers=_auth(admin))
    ended = await _competition(client, admin)
    await client.post(f"/api/competitions/{ended}/start", headers=_auth(admin))
    await client.post(f"/api/competitions/{ended}/stop", headers=_auth(admin))
    scheduled = await _competition(client, admin, start_at="2999-01-01T00:00:00Z")
    archived = await _competition(client, admin)
    await client.post(f"/api/competitions/{archived}/archive", headers=_auth(admin))

    overview = (await client.get("/api/admin/overview", headers=_auth(admin))).json()
    by_id = {c["id"]: c["status"] for c in overview["competitions"]}
    assert by_id[running] == "running"
    assert by_id[ended] == "ended"
    assert by_id[scheduled] == "scheduled"
    assert by_id[archived] == "archived"
    assert overview["archived_competitions"] == 1
    assert overview["active_competitions"] == 3


async def test_overview_requires_global_permission(client):
    admin = await admin_token(client)
    await _competition(client, admin)
    # A plain participant (or even a competition Judge) lacks view_global_analytics.
    token = await _register(client, "nobody@example.com")
    resp = await client.get("/api/admin/overview", headers=_auth(token))
    assert resp.status_code == 403
