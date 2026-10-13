"""Competition invite links (#427).

Organiser lifecycle (create / list / revoke under ``manage_invite_links``), the
public token-addressed resolve + join surface, and — the security heart of the
feature — every fail-closed path: revoked, expired, used-up, view links on a
competition that is no longer publicly visible, and cross-tenant link ids.
"""

from datetime import timedelta

from sqlalchemy import select

from auth.deps import user_has_permission
from db import SessionLocal, utcnow
from models.audit_log import AuditLogEntry
from models.invite_link import InviteLink
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email, name="User") -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": name},
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _make_competition(
    client, *, visibility="public", mode="individual", public_scoreboard=False
) -> tuple[dict, str]:
    admin = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={
            "name": "CTF",
            "participation_mode": mode,
            "visibility": visibility,
            "public_scoreboard": public_scoreboard,
        },
        headers=_auth(admin),
    )
    return resp.json(), admin


async def _make_link(client, admin, competition_id, **overrides) -> dict:
    body = {"capability": "join", **overrides}
    resp = await client.post(
        f"/api/competitions/{competition_id}/invite-links",
        json=body,
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _audit_count(event_name: str) -> int:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.event_name == event_name)
            )
        ).scalars().all()
    return len(rows)


# ---- organiser surface ----------------------------------------------------------


async def test_create_join_link_returns_token_and_emits(client):
    comp, admin = await _make_competition(client, visibility="private")
    link = await _make_link(client, admin, comp["id"], label="sponsor email")
    assert link["capability"] == "join"
    assert link["active"] is True
    assert link["use_count"] == 0
    assert link["label"] == "sponsor email"
    # The token is a real secret, not the competition's permanent invite code.
    assert link["token"] and link["token"] != comp["invite_code"]
    assert await _audit_count("invite_link.created") == 1


async def test_create_requires_manage_invite_links(client):
    comp, _admin = await _make_competition(client)
    token, _ = await _register(client, "pleb@example.com")
    resp = await client.post(
        f"/api/competitions/{comp['id']}/invite-links",
        json={"capability": "join"},
        headers=_auth(token),
    )
    assert resp.status_code == 403
    resp = await client.get(
        f"/api/competitions/{comp['id']}/invite-links", headers=_auth(token)
    )
    assert resp.status_code == 403


async def test_view_link_rejected_for_private_competition(client):
    comp, admin = await _make_competition(client, visibility="private")
    resp = await client.post(
        f"/api/competitions/{comp['id']}/invite-links",
        json={"capability": "view"},
        headers=_auth(admin),
    )
    assert resp.status_code == 422


async def test_past_expiry_rejected_at_creation(client):
    comp, admin = await _make_competition(client)
    resp = await client.post(
        f"/api/competitions/{comp['id']}/invite-links",
        json={
            "capability": "join",
            "expires_at": (utcnow() - timedelta(hours=1)).isoformat(),
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 422


async def test_list_and_revoke(client):
    comp, admin = await _make_competition(client)
    link = await _make_link(client, admin, comp["id"])
    resp = await client.get(
        f"/api/competitions/{comp['id']}/invite-links", headers=_auth(admin)
    )
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == [link["id"]]

    resp = await client.post(
        f"/api/competitions/{comp['id']}/invite-links/{link['id']}/revoke",
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["revoked_at"] is not None
    assert resp.json()["active"] is False
    assert await _audit_count("invite_link.revoked") == 1

    # Revoking twice is idempotent and doesn't re-emit.
    await client.post(
        f"/api/competitions/{comp['id']}/invite-links/{link['id']}/revoke",
        headers=_auth(admin),
    )
    assert await _audit_count("invite_link.revoked") == 1


async def test_revoke_cross_tenant_link_id_404s(client):
    comp_a, admin = await _make_competition(client)
    comp_b_resp = await client.post(
        "/api/competitions",
        json={"name": "Other", "participation_mode": "individual"},
        headers=_auth(admin),
    )
    comp_b = comp_b_resp.json()
    link = await _make_link(client, admin, comp_a["id"])
    # A real link id addressed through the wrong competition is indistinguishable
    # from a missing one (§6.2 cross-tenant guard).
    resp = await client.post(
        f"/api/competitions/{comp_b['id']}/invite-links/{link['id']}/revoke",
        headers=_auth(admin),
    )
    assert resp.status_code == 404


# ---- public resolve -------------------------------------------------------------


async def test_resolve_join_link_unauthenticated(client):
    comp, admin = await _make_competition(client, visibility="private")
    link = await _make_link(client, admin, comp["id"])
    resp = await client.get(f"/api/invite-links/{link['token']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["capability"] == "join"
    assert body["competition_name"] == "CTF"
    assert body["requires_login"] is True
    assert body["actionable"] is True  # auto-started to running by conftest
    assert "token" not in body and "use_count" not in body


async def test_resolve_unknown_token_404s(client):
    resp = await client.get("/api/invite-links/not-a-real-token")
    assert resp.status_code == 404


async def test_resolve_revoked_and_expired_fail_closed(client):
    comp, admin = await _make_competition(client)
    revoked = await _make_link(client, admin, comp["id"])
    await client.post(
        f"/api/competitions/{comp['id']}/invite-links/{revoked['id']}/revoke",
        headers=_auth(admin),
    )
    assert (await client.get(f"/api/invite-links/{revoked['token']}")).status_code == 404

    expired = await _make_link(client, admin, comp["id"])
    async with SessionLocal() as session:
        row = await session.get(InviteLink, expired["id"])
        row.expires_at = utcnow() - timedelta(minutes=1)
        await session.commit()
    assert (await client.get(f"/api/invite-links/{expired['token']}")).status_code == 404


async def test_view_link_resolves_and_fails_closed_on_visibility_flip(client):
    comp, admin = await _make_competition(
        client, visibility="public", public_scoreboard=True
    )
    link = await _make_link(client, admin, comp["id"], capability="view")
    resp = await client.get(f"/api/invite-links/{link['token']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["capability"] == "view"
    assert resp.json()["requires_login"] is False
    assert resp.json()["actionable"] is True

    # Turning the competition private kills the outstanding view link — fail
    # closed on *current* state, never stamped at creation (#427).
    await client.patch(
        f"/api/competitions/{comp['id']}",
        json={"visibility": "private"},
        headers=_auth(admin),
    )
    assert (await client.get(f"/api/invite-links/{link['token']}")).status_code == 404

    # ...and so does hiding the public scoreboard while staying public.
    await client.patch(
        f"/api/competitions/{comp['id']}",
        json={"visibility": "public", "public_scoreboard": False},
        headers=_auth(admin),
    )
    assert (await client.get(f"/api/invite-links/{link['token']}")).status_code == 404


async def test_view_link_without_public_scoreboard_does_not_resolve(client):
    comp, admin = await _make_competition(
        client, visibility="public", public_scoreboard=False
    )
    link = await _make_link(client, admin, comp["id"], capability="view")
    # Creatable (organiser may enable the board later) but resolves 404 until the
    # spectator surface it fronts actually exists.
    assert (await client.get(f"/api/invite-links/{link['token']}")).status_code == 404


# ---- public join ----------------------------------------------------------------


async def test_join_via_link_grants_membership_and_counts_use(client):
    comp, admin = await _make_competition(client, visibility="private")
    link = await _make_link(client, admin, comp["id"])
    token, user_id = await _register(client, "linked@example.com")

    resp = await client.post(
        f"/api/invite-links/{link['token']}/join", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == comp["id"]
    async with SessionLocal() as session:
        assert await user_has_permission(session, user_id, "challenge_view", comp["id"])
    assert await _audit_count("competition.member_joined") == 1

    # A member re-clicking their link neither re-emits nor burns a use.
    await client.post(f"/api/invite-links/{link['token']}/join", headers=_auth(token))
    assert await _audit_count("competition.member_joined") == 1
    listing = await client.get(
        f"/api/competitions/{comp['id']}/invite-links", headers=_auth(admin)
    )
    assert listing.json()[0]["use_count"] == 1


async def test_join_requires_login(client):
    comp, admin = await _make_competition(client)
    link = await _make_link(client, admin, comp["id"])
    resp = await client.post(f"/api/invite-links/{link['token']}/join")
    assert resp.status_code == 401


async def test_join_via_view_link_404s(client):
    comp, admin = await _make_competition(
        client, visibility="public", public_scoreboard=True
    )
    link = await _make_link(client, admin, comp["id"], capability="view")
    token, _ = await _register(client, "watcher@example.com")
    resp = await client.post(
        f"/api/invite-links/{link['token']}/join", headers=_auth(token)
    )
    assert resp.status_code == 404


async def test_join_via_revoked_link_404s(client):
    comp, admin = await _make_competition(client, visibility="private")
    link = await _make_link(client, admin, comp["id"])
    await client.post(
        f"/api/competitions/{comp['id']}/invite-links/{link['id']}/revoke",
        headers=_auth(admin),
    )
    token, _ = await _register(client, "late@example.com")
    resp = await client.post(
        f"/api/invite-links/{link['token']}/join", headers=_auth(token)
    )
    assert resp.status_code == 404


async def test_max_uses_admits_exactly_that_many(client):
    comp, admin = await _make_competition(client, visibility="private")
    link = await _make_link(client, admin, comp["id"], max_uses=1)
    first, _ = await _register(client, "first@example.com", name="First")
    second, _ = await _register(client, "second@example.com", name="Second")

    resp = await client.post(
        f"/api/invite-links/{link['token']}/join", headers=_auth(first)
    )
    assert resp.status_code == 200, resp.text
    # Used up: resolve and join both fail closed for the next person.
    assert (await client.get(f"/api/invite-links/{link['token']}")).status_code == 404
    resp = await client.post(
        f"/api/invite-links/{link['token']}/join", headers=_auth(second)
    )
    assert resp.status_code == 404


async def test_archived_competition_kills_links_entirely(client):
    comp, admin = await _make_competition(client, visibility="private")
    link = await _make_link(client, admin, comp["id"])
    await client.post(f"/api/competitions/{comp['id']}/archive", headers=_auth(admin))

    # Archived = retired from view: both the landing and the join fail closed,
    # unlike `ended` (which still resolves so the landing can explain itself).
    assert (await client.get(f"/api/invite-links/{link['token']}")).status_code == 404
    token, _ = await _register(client, "archived@example.com")
    resp = await client.post(
        f"/api/invite-links/{link['token']}/join", headers=_auth(token)
    )
    assert resp.status_code == 404


async def test_ended_competition_blocks_join_but_still_resolves(client):
    comp, admin = await _make_competition(client, visibility="private")
    link = await _make_link(client, admin, comp["id"])
    await client.post(f"/api/competitions/{comp['id']}/stop", headers=_auth(admin))

    # The landing can still explain itself (actionable=False)...
    resp = await client.get(f"/api/invite-links/{link['token']}")
    assert resp.status_code == 200
    assert resp.json()["competition_status"] == "ended"
    assert resp.json()["actionable"] is False

    # ...but the link no longer admits anyone (#427, decision 4).
    token, _ = await _register(client, "tardy@example.com")
    resp = await client.post(
        f"/api/invite-links/{link['token']}/join", headers=_auth(token)
    )
    assert resp.status_code == 403


# ---- Phase 4: registration window + audit (#427) ----------------------------------


async def test_registration_window_gates_link_join(client):
    comp, admin = await _make_competition(client, visibility="private")
    link = await _make_link(client, admin, comp["id"])

    # Not open yet: the landing explains it, the join is refused.
    await client.patch(
        f"/api/competitions/{comp['id']}",
        json={"registration_opens_at": (utcnow() + timedelta(hours=1)).isoformat()},
        headers=_auth(admin),
    )
    resp = await client.get(f"/api/invite-links/{link['token']}")
    assert resp.status_code == 200
    assert resp.json()["actionable"] is False
    assert resp.json()["reason"] == "registration_not_open"
    token, _ = await _register(client, "early@example.com", name="Early")
    resp = await client.post(
        f"/api/invite-links/{link['token']}/join", headers=_auth(token)
    )
    assert resp.status_code == 403
    assert "hasn't opened" in resp.json()["detail"]

    # Open window: admits.
    await client.patch(
        f"/api/competitions/{comp['id']}",
        json={
            "registration_opens_at": (utcnow() - timedelta(hours=1)).isoformat(),
            "registration_closes_at": (utcnow() + timedelta(hours=1)).isoformat(),
        },
        headers=_auth(admin),
    )
    assert (await client.get(f"/api/invite-links/{link['token']}")).json()[
        "actionable"
    ] is True
    resp = await client.post(
        f"/api/invite-links/{link['token']}/join", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text

    # Closed: refused again — but the member it already admitted is unaffected.
    await client.patch(
        f"/api/competitions/{comp['id']}",
        json={"registration_closes_at": (utcnow() - timedelta(minutes=1)).isoformat()},
        headers=_auth(admin),
    )
    resp = await client.get(f"/api/invite-links/{link['token']}")
    assert resp.json()["reason"] == "registration_closed"
    late, _ = await _register(client, "late2@example.com", name="Late")
    resp = await client.post(
        f"/api/invite-links/{link['token']}/join", headers=_auth(late)
    )
    assert resp.status_code == 403
    assert "has closed" in resp.json()["detail"]


async def test_registration_window_does_not_gate_code_or_public_join(client):
    """The window gates the LINK path only (#427 Phase 4) — the permanent
    invite-code and lobby paths keep their released behaviour; widening is a
    separate decision."""
    comp, admin = await _make_competition(client, visibility="public")
    await client.patch(
        f"/api/competitions/{comp['id']}",
        json={"registration_closes_at": (utcnow() - timedelta(hours=1)).isoformat()},
        headers=_auth(admin),
    )
    token, _ = await _register(client, "codepath@example.com", name="CodePath")
    resp = await client.post(
        "/api/competitions/join",
        json={"invite_code": comp["invite_code"]},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text


async def test_join_stamps_last_used_and_emits_used_event(client):
    comp, admin = await _make_competition(client, visibility="private")
    link = await _make_link(client, admin, comp["id"])
    assert link["last_used_at"] is None

    token, user_id = await _register(client, "stamped@example.com", name="Stamped")
    await client.post(f"/api/invite-links/{link['token']}/join", headers=_auth(token))
    rows = (
        await client.get(
            f"/api/competitions/{comp['id']}/invite-links", headers=_auth(admin)
        )
    ).json()
    first_stamp = rows[0]["last_used_at"]
    assert first_stamp is not None
    assert await _audit_count("invite_link.used") == 1

    # A member re-clicking is not a "use": no new event, stamp unchanged.
    await client.post(f"/api/invite-links/{link['token']}/join", headers=_auth(token))
    rows = (
        await client.get(
            f"/api/competitions/{comp['id']}/invite-links", headers=_auth(admin)
        )
    ).json()
    assert rows[0]["last_used_at"] == first_stamp
    assert await _audit_count("invite_link.used") == 1
