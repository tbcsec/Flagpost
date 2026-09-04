"""Team endpoints: membership rules, mode gating, scoping, events (ROADMAP #7)."""

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email, name=None) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": name or email.split("@")[0],
        },
    )
    return resp.json()["access_token"]


async def _make_competition(client, mode="team", visibility="public") -> str:
    # Public by default: self-serve create_team is only allowed for a competition
    # the caller can already see (GHSA-4mmf). A private competition is exercised
    # explicitly by the access-control tests below.
    token = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={
            "name": f"Comp-{mode}",
            "participation_mode": mode,
            "visibility": visibility,
        },
        headers=_auth(token),
    )
    return resp.json()["id"]


async def _events(name: str):
    async with SessionLocal() as session:
        return (
            await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.event_name == name)
            )
        ).scalars().all()


async def test_create_team_makes_creator_captain_and_emits_event(client):
    comp = await _make_competition(client)
    alice = await _register(client, "alice@example.com", "Alice")

    resp = await client.post(
        f"/api/competitions/{comp}/teams",
        json={"name": "Red Team"},
        headers=_auth(alice),
    )
    assert resp.status_code == 201
    team = resp.json()
    assert team["name"] == "Red Team"
    assert team["invite_code"]
    assert team["members"][0]["display_name"] == "Alice"
    assert team["members"][0]["is_captain"] is True

    events = await _events("team.created")
    assert len(events) == 1
    assert events[0].competition_id == comp


async def test_individual_mode_competition_rejects_team_creation(client):
    comp = await _make_competition(client, mode="individual")
    user = await _register(client, "solo@example.com")

    resp = await client.post(
        f"/api/competitions/{comp}/teams",
        json={"name": "Not Allowed"},
        headers=_auth(user),
    )
    assert resp.status_code == 400


async def test_join_via_invite_code_and_one_team_per_competition(client):
    comp = await _make_competition(client)
    alice = await _register(client, "alice@example.com", "Alice")
    bob = await _register(client, "bob@example.com", "Bob")

    created = (
        await client.post(
            f"/api/competitions/{comp}/teams",
            json={"name": "Red Team"},
            headers=_auth(alice),
        )
    ).json()

    joined = await client.post(
        f"/api/competitions/{comp}/teams/join",
        json={"invite_code": created["invite_code"]},
        headers=_auth(bob),
    )
    assert joined.status_code == 200
    assert joined.json()["pending"] is False
    assert [m["display_name"] for m in joined.json()["team"]["members"]] == ["Alice", "Bob"]
    assert len(await _events("team.member_joined")) == 1

    # Bob can't create or join a second team in the same competition.
    second = await client.post(
        f"/api/competitions/{comp}/teams",
        json={"name": "Blue Team"},
        headers=_auth(bob),
    )
    assert second.status_code == 409

    # A wrong code 404s.
    bad = await client.post(
        f"/api/competitions/{comp}/teams/join",
        json={"invite_code": "not-a-code"},
        headers=_auth(await _register(client, "carol@example.com")),
    )
    assert bad.status_code == 404


async def test_invite_code_is_scoped_to_its_competition(client):
    comp_a = await _make_competition(client)
    admin = await admin_token(client)
    comp_b = (
        await client.post(
            "/api/competitions",
            json={"name": "Other Comp", "participation_mode": "team"},
            headers=_auth(admin),
        )
    ).json()["id"]

    alice = await _register(client, "alice@example.com")
    code = (
        await client.post(
            f"/api/competitions/{comp_a}/teams",
            json={"name": "Red Team"},
            headers=_auth(alice),
        )
    ).json()["invite_code"]

    # The code belongs to comp_a; using it in comp_b must not match (§6.2).
    bob = await _register(client, "bob@example.com")
    resp = await client.post(
        f"/api/competitions/{comp_b}/teams/join",
        json={"invite_code": code},
        headers=_auth(bob),
    )
    assert resp.status_code == 404


async def test_listing_shows_counts_but_never_invite_codes(client):
    comp = await _make_competition(client)
    alice = await _register(client, "alice@example.com")
    await client.post(
        f"/api/competitions/{comp}/teams",
        json={"name": "Red Team"},
        headers=_auth(alice),
    )

    listed = await client.get(
        f"/api/competitions/{comp}/teams", headers=_auth(alice)
    )
    assert listed.status_code == 200
    [team] = listed.json()
    assert team["member_count"] == 1
    assert "invite_code" not in team


async def test_leave_promotes_next_captain_then_deletes_empty_team(client):
    comp = await _make_competition(client)
    alice = await _register(client, "alice@example.com", "Alice")
    bob = await _register(client, "bob@example.com", "Bob")

    created = (
        await client.post(
            f"/api/competitions/{comp}/teams",
            json={"name": "Red Team"},
            headers=_auth(alice),
        )
    ).json()
    await client.post(
        f"/api/competitions/{comp}/teams/join",
        json={"invite_code": created["invite_code"]},
        headers=_auth(bob),
    )

    # Captain (Alice) leaves -> Bob is promoted.
    left = await client.post(
        f"/api/competitions/{comp}/teams/leave", headers=_auth(alice)
    )
    assert left.status_code == 204
    mine = (
        await client.get(f"/api/competitions/{comp}/teams/me", headers=_auth(bob))
    ).json()
    assert mine["members"] == [
        {"user_id": mine["members"][0]["user_id"], "display_name": "Bob", "is_captain": True}
    ]

    # Last member leaves -> team is deleted and both events fire.
    await client.post(f"/api/competitions/{comp}/teams/leave", headers=_auth(bob))
    listed = await client.get(
        f"/api/competitions/{comp}/teams", headers=_auth(bob)
    )
    assert listed.json() == []
    assert len(await _events("team.member_left")) == 2
    assert len(await _events("team.deleted")) == 1

    # Alice, now teamless, gets a 404 from /me.
    resp = await client.get(
        f"/api/competitions/{comp}/teams/me", headers=_auth(alice)
    )
    assert resp.status_code == 404


async def test_joining_a_team_grants_participant_access(client):
    """Team membership is how a competitor gains competition access (§7.5, Phase
    6): creating or joining a team grants the viewer-level Participant role, so
    challenge_view (and thus flag submission) works without a separate join step."""
    from auth.deps import user_has_permission

    comp = await _make_competition(client)
    alice = await _register(client, "alice@example.com", "Alice")
    created = await client.post(
        f"/api/competitions/{comp}/teams",
        json={"name": "Red Team"},
        headers=_auth(alice),
    )
    creator_id = created.json()["members"][0]["user_id"]
    code = created.json()["invite_code"]

    bob = await _register(client, "bob@example.com", "Bob")
    joined = await client.post(
        f"/api/competitions/{comp}/teams/join",
        json={"invite_code": code},
        headers=_auth(bob),
    )
    joiner_id = next(
        m["user_id"] for m in joined.json()["team"]["members"] if m["display_name"] == "Bob"
    )

    async with SessionLocal() as session:
        assert await user_has_permission(session, creator_id, "challenge_view", comp)
        assert await user_has_permission(session, joiner_id, "challenge_view", comp)
        # ...but only for this competition, never site-wide (§7.5).
        assert not await user_has_permission(
            session, creator_id, "challenge_view", None
        )


# --- team QoL: size cap + profile (Phase 9, Group C) -------------------------


async def test_max_team_size_blocks_join_when_full(client):
    admin = await admin_token(client)
    comp = (await client.post("/api/competitions", json={"name": "Capped", "participation_mode": "team", "max_team_size": 2, "visibility": "public"}, headers=_auth(admin))).json()["id"]
    cap = await _register(client, "cap@example.com", "Cap")
    team = (await client.post(f"/api/competitions/{comp}/teams", json={"name": "Duo"}, headers=_auth(cap))).json()
    code = team["invite_code"]

    m2 = await _register(client, "m2@example.com")
    assert (await client.post(f"/api/competitions/{comp}/teams/join", json={"invite_code": code}, headers=_auth(m2))).status_code == 200
    # Third member is refused — team is full at 2.
    m3 = await _register(client, "m3@example.com")
    resp = await client.post(f"/api/competitions/{comp}/teams/join", json={"invite_code": code}, headers=_auth(m3))
    assert resp.status_code == 409


async def test_captain_edits_team_profile(client):
    comp = await _make_competition(client)
    cap = await _register(client, "cap@example.com", "Cap")
    await client.post(f"/api/competitions/{comp}/teams", json={"name": "Profs", "affiliation": "MIT"}, headers=_auth(cap))
    resp = await client.patch(
        f"/api/competitions/{comp}/teams/me",
        json={"country": "US", "website": "https://x.example"},
        headers=_auth(cap),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["affiliation"] == "MIT" and body["country"] == "US" and body["website"] == "https://x.example"

    # A non-captain member can't edit.
    member = await _register(client, "member@example.com")
    code = (await client.get(f"/api/competitions/{comp}/teams/me", headers=_auth(cap))).json()["invite_code"]
    await client.post(f"/api/competitions/{comp}/teams/join", json={"invite_code": code}, headers=_auth(member))
    assert (await client.patch(f"/api/competitions/{comp}/teams/me", json={"country": "CA"}, headers=_auth(member))).status_code == 403


async def test_approval_required_team_files_request_and_captain_approves(client):
    comp = await _make_competition(client)
    cap = await _register(client, "cap@example.com", "Cap")
    team = (await client.post(f"/api/competitions/{comp}/teams", json={"name": "Gated", "approval_required": True}, headers=_auth(cap))).json()
    code = team["invite_code"]

    # Joining files a pending request, not an immediate membership.
    applicant = await _register(client, "app@example.com", "Applicant")
    joined = await client.post(f"/api/competitions/{comp}/teams/join", json={"invite_code": code}, headers=_auth(applicant))
    assert joined.status_code == 200
    assert joined.json() == {"pending": True, "team": None}
    # Not yet a member.
    assert (await client.get(f"/api/competitions/{comp}/teams/me", headers=_auth(applicant))).status_code == 404

    # The captain sees the request and approves it.
    reqs = (await client.get(f"/api/competitions/{comp}/teams/me/requests", headers=_auth(cap))).json()
    assert len(reqs) == 1 and reqs[0]["display_name"] == "Applicant"
    approve = await client.post(f"/api/competitions/{comp}/teams/me/requests/{reqs[0]['id']}/approve", headers=_auth(cap))
    assert approve.status_code == 200
    assert {m["display_name"] for m in approve.json()["members"]} == {"Cap", "Applicant"}

    # Applicant is now on the team; the request is gone.
    assert (await client.get(f"/api/competitions/{comp}/teams/me", headers=_auth(applicant))).status_code == 200
    assert (await client.get(f"/api/competitions/{comp}/teams/me/requests", headers=_auth(cap))).json() == []


async def test_only_captain_reviews_requests(client):
    comp = await _make_competition(client)
    cap = await _register(client, "cap@example.com")
    await client.post(f"/api/competitions/{comp}/teams", json={"name": "T", "approval_required": True}, headers=_auth(cap))
    outsider = await _register(client, "out@example.com")
    assert (await client.get(f"/api/competitions/{comp}/teams/me/requests", headers=_auth(outsider))).status_code == 403


async def _make_private_competition(client) -> dict:
    """Return the full create response (id + invite_code, visible to the creator)
    for a private team competition."""
    token = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={"name": "Private", "participation_mode": "team", "visibility": "private"},
        headers=_auth(token),
    )
    return resp.json()


async def test_create_team_on_private_competition_blocks_non_member(client):
    """GHSA-4mmf: a private competition must not be enterable by POSTing a team
    with just its id — before the fix this granted Participant + full competitor
    access without the invite code. It now 404s (existence undisclosed), and the
    roster listing does too."""
    comp = await _make_private_competition(client)
    stranger = await _register(client, "stranger@example.com", "Stranger")

    resp = await client.post(
        f"/api/competitions/{comp['id']}/teams",
        json={"name": "Intruder"},
        headers=_auth(stranger),
    )
    assert resp.status_code == 404

    listing = await client.get(
        f"/api/competitions/{comp['id']}/teams", headers=_auth(stranger)
    )
    assert listing.status_code == 404


async def test_create_team_on_private_competition_allowed_after_joining_by_code(client):
    """The legitimate flow the gate preserves: a competitor who joined the private
    competition with its invite code may then create a team and see the roster."""
    comp = await _make_private_competition(client)
    member = await _register(client, "member@example.com", "Member")

    joined = await client.post(
        "/api/competitions/join",
        json={"invite_code": comp["invite_code"]},
        headers=_auth(member),
    )
    assert joined.status_code == 200

    created = await client.post(
        f"/api/competitions/{comp['id']}/teams",
        json={"name": "Legit"},
        headers=_auth(member),
    )
    assert created.status_code == 201

    listing = await client.get(
        f"/api/competitions/{comp['id']}/teams", headers=_auth(member)
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1
