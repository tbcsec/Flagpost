"""Delegated account and role management can't reach above the delegate
(GHSA-mwhq-j3jg-p339).

``manage_users`` and ``manage_roles`` hand out administration of accounts and
roles, not everything: a delegate acts only on accounts and assignments holding
no privilege they lack themselves — the rule the role editor already applies to
grants (GHSA-mgh6).
"""

from sqlalchemy import select

from db import SessionLocal
from models.role import Role, RoleAssignment
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, name: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={"email": f"{name}@example.com", "password": "password123", "display_name": name},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _grant_global(user_id: str, name: str, permissions: list[str]) -> str:
    async with SessionLocal() as db:
        role = Role(name=name, scope="global", permissions=permissions)
        db.add(role)
        await db.flush()
        db.add(RoleAssignment(user_id=user_id, competition_id=None, role_id=role.id))
        await db.commit()
        return role.id


async def _me(client, token: str) -> str:
    return (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]


async def _roles(client, token: str) -> dict:
    return {r["name"]: r for r in (await client.get("/api/roles", headers=_auth(token))).json()}


async def _help_desk(client) -> str:
    token, user_id = await _register(client, "helpdesk")
    await _grant_global(user_id, "Help desk", ["manage_users", "view_all_users"])
    return token


async def test_user_delegate_cannot_take_over_an_administrator(client):
    admin = await admin_token(client)
    admin_id = await _me(client, admin)
    desk = await _help_desk(client)

    for body in ({"password": "takeover-123"}, {"email": "desk@evil.example"}, {"display_name": "x"}):
        resp = await client.patch(f"/api/users/{admin_id}", json=body, headers=_auth(desk))
        assert resp.status_code == 403, (body, resp.text)
    for path in (f"/api/users/{admin_id}/ban", f"/api/users/{admin_id}/unban"):
        resp = await client.post(path, headers=_auth(desk))
        assert resp.status_code == 403, (path, resp.text)
    gone = await client.delete(f"/api/users/{admin_id}", headers=_auth(desk))
    assert gone.status_code == 403, gone.text

    # The administrator's credentials are untouched.
    login = await client.post(
        "/api/auth/login", json={"identifier": "admin@example.com", "password": "changeme"}
    )
    assert login.status_code == 200, login.text


async def test_user_delegate_still_manages_ordinary_players(client):
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "Open", "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()
    player, player_id = await _register(client, "player")
    joined = await client.post(f"/api/competitions/{comp['id']}/join", headers=_auth(player))
    assert joined.status_code == 200, joined.text
    desk = await _help_desk(client)

    # A Participant's floor grants aren't privilege: a help desk resets them.
    reset = await client.patch(
        f"/api/users/{player_id}", json={"password": "fresh-password-1"}, headers=_auth(desk)
    )
    assert reset.status_code == 200, reset.text
    banned = await client.post(f"/api/users/{player_id}/ban", headers=_auth(desk))
    assert banned.status_code == 200, banned.text


async def test_user_delegate_cannot_take_over_a_judge(client):
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions", json={"name": "Run", "visibility": "public"}, headers=_auth(admin)
        )
    ).json()
    _, judge_id = await _register(client, "judge1")
    assigned = await client.post(
        "/api/roles/assignments",
        json={
            "email": "judge1@example.com",
            "role_id": (await _roles(client, admin))["Judge"]["id"],
            "competition_id": comp["id"],
        },
        headers=_auth(admin),
    )
    assert assigned.status_code == 201, assigned.text
    desk = await _help_desk(client)

    resp = await client.patch(
        f"/api/users/{judge_id}", json={"password": "takeover-123"}, headers=_auth(desk)
    )
    assert resp.status_code == 403, resp.text

    # An Administrator still can.
    ok = await client.patch(
        f"/api/users/{judge_id}", json={"password": "reset-by-admin-1"}, headers=_auth(admin)
    )
    assert ok.status_code == 200, ok.text


async def test_role_delegate_cannot_demote_an_administrator(client):
    admin = await admin_token(client)
    roles = await _roles(client, admin)
    # A second administrator, so the last-admin guard isn't what refuses.
    _, other_id = await _register(client, "second")
    second = await client.post(
        "/api/roles/assignments",
        json={"email": "second@example.com", "role_id": roles["Administrator"]["id"]},
        headers=_auth(admin),
    )
    assert second.status_code == 201, second.text
    rolesmith, rolesmith_id = await _register(client, "rolesmith")
    await _grant_global(rolesmith_id, "Role desk", ["manage_roles"])

    resp = await client.delete(
        f"/api/roles/assignments/{second.json()['id']}", headers=_auth(rolesmith)
    )
    assert resp.status_code == 403, resp.text
    assert "manage_users" in resp.json()["detail"]

    # What they hold, they can take away: their own role, from a colleague.
    _, colleague_id = await _register(client, "colleague")
    peer_role = await _grant_global(colleague_id, "Peer desk", ["manage_roles"])
    async with SessionLocal() as db:
        peer_assignment = await db.scalar(
            select(RoleAssignment.id).where(RoleAssignment.role_id == peer_role)
        )
    removed = await client.delete(
        f"/api/roles/assignments/{peer_assignment}", headers=_auth(rolesmith)
    )
    assert removed.status_code == 204, removed.text


async def test_role_delegate_cannot_strip_permissions_it_lacks(client):
    admin = await admin_token(client)
    broad = await client.post(
        "/api/roles",
        json={"name": "Ops", "scope": "global", "permissions": ["manage_pages", "manage_roles"]},
        headers=_auth(admin),
    )
    assert broad.status_code == 201, broad.text
    rolesmith, rolesmith_id = await _register(client, "editor")
    await _grant_global(rolesmith_id, "Role desk", ["manage_roles"])
    role_id = broad.json()["id"]

    narrowed = await client.patch(
        f"/api/roles/{role_id}", json={"permissions": ["manage_roles"]}, headers=_auth(rolesmith)
    )
    assert narrowed.status_code == 403, narrowed.text
    assert "manage_pages" in narrowed.json()["detail"]

    # A rename takes nothing away and stays allowed.
    renamed = await client.patch(
        f"/api/roles/{role_id}", json={"description": "operations"}, headers=_auth(rolesmith)
    )
    assert renamed.status_code == 200, renamed.text
