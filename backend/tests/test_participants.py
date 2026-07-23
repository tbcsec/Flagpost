"""Individual-mode participant roster (Phase 9, ROADMAP #7 counterpart to teams):
the roster lists Participant-role holders with standing + solve count, scoped and
gated on challenge_view."""

from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def _individual_competition(client) -> str:
    admin = await admin_token(client)
    return (
        await client.post(
            "/api/competitions",
            json={"name": "Solo CTF", "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _published_challenge(client, comp, flag="flag{a}", points=100) -> str:
    admin = await admin_token(client)
    cid = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": f"Chal {flag}", "points": points, "flag": flag},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/publish", headers=_auth(admin)
    )
    return cid


async def _join(client, comp, email) -> str:
    token = await _register(client, email)
    resp = await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return token


async def test_roster_lists_joined_participants_with_standing(client):
    comp = await _individual_competition(client)
    chal = await _published_challenge(client, comp, "flag{a}", 100)
    ada = await _join(client, comp, "ada@example.com")
    await _join(client, comp, "bob@example.com")

    # Ada solves; Bob hasn't.
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{a}"},
        headers=_auth(ada),
    )

    roster = (
        await client.get(f"/api/competitions/{comp}/participants", headers=_auth(ada))
    ).json()
    assert len(roster) == 2
    by_name = {p["display_name"]: p for p in roster}

    assert by_name["ada"]["rank"] == 1
    assert by_name["ada"]["points"] == 100
    assert by_name["ada"]["solve_count"] == 1
    assert by_name["ada"]["joined_at"] is not None

    # Bob is on the roster with no solves — ranked below Ada.
    assert by_name["bob"]["points"] == 0
    assert by_name["bob"]["solve_count"] == 0
    assert roster[0]["display_name"] == "ada"  # ranked participant first


async def test_roster_requires_competition_access(client):
    comp = await _individual_competition(client)
    outsider = await _register(client, "outsider@example.com")  # never joined
    resp = await client.get(
        f"/api/competitions/{comp}/participants", headers=_auth(outsider)
    )
    assert resp.status_code == 403


async def test_roster_scoped_to_competition(client):
    comp_a = await _individual_competition(client)
    comp_b = await _individual_competition(client)
    await _join(client, comp_a, "only-a@example.com")
    b_player = await _join(client, comp_b, "only-b@example.com")

    # A participant of B sees only B's roster (their own competition).
    roster_b = (
        await client.get(
            f"/api/competitions/{comp_b}/participants", headers=_auth(b_player)
        )
    ).json()
    assert [p["display_name"] for p in roster_b] == ["only-b"]


async def test_missing_competition_is_404(client):
    admin = await admin_token(client)
    resp = await client.get(
        "/api/competitions/does-not-exist/participants", headers=_auth(admin)
    )
    assert resp.status_code == 404


# --- manual awards (§5.3 create-award counterpart) ---------------------------


async def test_judge_awards_points_to_participants(client):
    comp = await _individual_competition(client)
    chal = await _published_challenge(client, comp, "flag{a}", 100)
    admin = await admin_token(client)
    ada = await _join(client, comp, "ada@example.com")
    await _join(client, comp, "bob@example.com")

    ada_id = (await client.get("/api/auth/me", headers=_auth(ada))).json()["id"]
    bob_id = next(
        p["user_id"]
        for p in (
            await client.get(f"/api/competitions/{comp}/participants", headers=_auth(admin))
        ).json()
        if p["display_name"] == "bob"
    )

    # Ada solves for 100; then both get a 50-point sportsmanship award.
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{a}"},
        headers=_auth(ada),
    )
    resp = await client.post(
        f"/api/competitions/{comp}/awards",
        json={
            "user_ids": [ada_id, bob_id],
            "title": "Good sport",
            "description": "Helped a teammate",
            "points": 50,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    assert len(resp.json()) == 2

    roster = {
        p["display_name"]: p
        for p in (
            await client.get(f"/api/competitions/{comp}/participants", headers=_auth(admin))
        ).json()
    }
    assert roster["ada"]["points"] == 150  # 100 solve + 50 award
    assert roster["bob"]["points"] == 50   # award only


async def test_award_requires_score_override(client):
    comp = await _individual_competition(client)
    ada = await _join(client, comp, "ada@example.com")
    ada_id = (await client.get("/api/auth/me", headers=_auth(ada))).json()["id"]
    resp = await client.post(
        f"/api/competitions/{comp}/awards",
        json={"user_ids": [ada_id], "title": "Nope", "points": 10},
        headers=_auth(ada),  # a participant, no score_override
    )
    assert resp.status_code == 403


async def test_award_rejects_non_participant(client):
    comp = await _individual_competition(client)
    admin = await admin_token(client)
    outsider = await _register(client, "outsider@example.com")  # never joined
    outsider_id = (await client.get("/api/auth/me", headers=_auth(outsider))).json()["id"]
    resp = await client.post(
        f"/api/competitions/{comp}/awards",
        json={"user_ids": [outsider_id], "title": "Nope", "points": 10},
        headers=_auth(admin),
    )
    assert resp.status_code == 400
