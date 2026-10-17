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
    # A second administrator, so ban/delete are refused by containment rather
    # than by the last-administrator guard.
    await _register(client, "spare")
    spare = await client.post(
        "/api/roles/assignments",
        json={"email": "spare@example.com", "role_id": (await _roles(client, admin))["Administrator"]["id"]},
        headers=_auth(admin),
    )
    assert spare.status_code == 201, spare.text
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


async def test_a_site_wide_floor_permission_is_still_privilege(client):
    # The Participant floor is subtracted from competition grants only: the
    # same key held site-wide reaches every competition.
    _, target_id = await _register(client, "observer")
    await _grant_global(target_id, "Observer", ["challenge_view"])
    desk = await _help_desk(client)
    resp = await client.patch(
        f"/api/users/{target_id}", json={"password": "takeover-123"}, headers=_auth(desk)
    )
    assert resp.status_code == 403, resp.text


async def test_a_desk_judging_one_competition_cannot_take_over_its_fellow_judge(client):
    # The actor's own competition grants don't count: containment compares
    # against what they hold site-wide.
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions", json={"name": "Shared", "visibility": "public"}, headers=_auth(admin)
        )
    ).json()
    judge_role = (await _roles(client, admin))["Judge"]["id"]
    desk, desk_id = await _register(client, "deskjudge")
    await _grant_global(desk_id, "Help desk", ["manage_users", "view_all_users"])
    _, other_id = await _register(client, "otherjudge")
    for email in ("deskjudge@example.com", "otherjudge@example.com"):
        r = await client.post(
            "/api/roles/assignments",
            json={"email": email, "role_id": judge_role, "competition_id": comp["id"]},
            headers=_auth(admin),
        )
        assert r.status_code == 201, r.text

    resp = await client.patch(
        f"/api/users/{other_id}", json={"password": "takeover-123"}, headers=_auth(desk)
    )
    assert resp.status_code == 403, resp.text
    # Acting on yourself is never an escalation.
    own = await client.patch(
        f"/api/users/{desk_id}", json={"display_name": "deskjudge2"}, headers=_auth(desk)
    )
    assert own.status_code == 200, own.text


async def test_role_delegate_cannot_unassign_a_competition_judge(client):
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions", json={"name": "Run2", "visibility": "public"}, headers=_auth(admin)
        )
    ).json()
    await _register(client, "judged")
    judge = await client.post(
        "/api/roles/assignments",
        json={
            "email": "judged@example.com",
            "role_id": (await _roles(client, admin))["Judge"]["id"],
            "competition_id": comp["id"],
        },
        headers=_auth(admin),
    )
    assert judge.status_code == 201, judge.text
    rolesmith, rolesmith_id = await _register(client, "unassigner")
    await _grant_global(rolesmith_id, "Role desk", ["manage_roles"])
    resp = await client.delete(
        f"/api/roles/assignments/{judge.json()['id']}", headers=_auth(rolesmith)
    )
    assert resp.status_code == 403, resp.text


async def test_a_stale_permission_key_never_locks_out_an_administrator(client):
    # A key no longer in the catalog grants nothing, so it confers nothing.
    admin = await admin_token(client)
    _, target_id = await _register(client, "stale")
    role_id = await _grant_global(target_id, "Stale", ["no_longer_a_permission"])
    patched = await client.patch(
        f"/api/users/{target_id}", json={"password": "reset-by-admin-1"}, headers=_auth(admin)
    )
    assert patched.status_code == 200, patched.text
    async with SessionLocal() as db:
        assignment = await db.scalar(
            select(RoleAssignment.id).where(RoleAssignment.role_id == role_id)
        )
    removed = await client.delete(f"/api/roles/assignments/{assignment}", headers=_auth(admin))
    assert removed.status_code == 204, removed.text


async def test_settings_delegate_cannot_redirect_mail_delivery(client):
    """Mail delivery carries every password-reset link, so pointing it at
    another server takes over any account: it needs an Administrator."""
    admin = await admin_token(client)
    token, user_id = await _register(client, "settingsdesk")
    await _grant_global(user_id, "Settings desk", ["manage_site_settings"])
    base = {"registration_open": True}

    for change in (
        {"smtp_host": "mail.attacker.example"},
        {"smtp_port": 2525},
        {"smtp_username": "me"},
        {"smtp_starttls": False},
        {"smtp_password": "secret"},
    ):
        resp = await client.put(
            "/api/site-settings/operational", json={**base, **change}, headers=_auth(token)
        )
        assert resp.status_code == 403, (change, resp.text)

    # Leaving the transport as it is keeps the rest of the page theirs.
    ok = await client.put(
        "/api/site-settings/operational",
        json={**base, "smtp_from": "ctf@example.com"},
        headers=_auth(token),
    )
    assert ok.status_code == 200, ok.text
    # An Administrator still configures it.
    by_admin = await client.put(
        "/api/site-settings/operational",
        json={**base, "smtp_host": "smtp.example.com"},
        headers=_auth(admin),
    )
    assert by_admin.status_code == 200, by_admin.text


async def test_assignment_by_id_lands_on_exactly_that_account(client):
    admin = await admin_token(client)
    _, picked_id = await _register(client, "picked")
    role = await client.post(
        "/api/roles",
        json={"name": "Pages", "scope": "global", "permissions": ["manage_pages"]},
        headers=_auth(admin),
    )
    resp = await client.post(
        "/api/roles/assignments",
        json={"user_id": picked_id, "role_id": role.json()["id"]},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user_id"] == picked_id
    both = await client.post(
        "/api/roles/assignments",
        json={"user_id": picked_id, "email": "picked@example.com", "role_id": role.json()["id"]},
        headers=_auth(admin),
    )
    assert both.status_code == 422, both.text


async def test_settings_delegate_cannot_redirect_mail_delivery_by_import(client):
    """The backup's site_settings section is no way around the Administrator
    bar on the mail transport."""
    admin = await admin_token(client)
    token, user_id = await _register(client, "importdesk")
    await _grant_global(user_id, "Settings desk", ["manage_site_settings"])

    export = await client.post(
        "/api/site-settings/export", json={"sections": ["site_settings"]}, headers=_auth(admin)
    )
    assert export.status_code == 200, export.text
    document = export.json()

    # Restoring the install's own settings unchanged is still theirs.
    same = await client.post(
        "/api/site-settings/import",
        json={"sections": ["site_settings"], "payload": document},
        headers=_auth(token),
    )
    assert same.status_code == 200, same.text

    (row,) = document["data"]["site_settings"]
    for change in (
        {"smtp_host": "mail.attacker.example"},
        {"smtp_port": 2525},
        {"smtp_password": "secret"},
    ):
        tampered = {**document, "data": {"site_settings": [{**row, **change}]}}
        resp = await client.post(
            "/api/site-settings/import",
            json={"sections": ["site_settings"], "payload": tampered},
            headers=_auth(token),
        )
        assert resp.status_code == 403, (change, resp.text)

    operational = await client.get("/api/site-settings/operational", headers=_auth(admin))
    assert operational.json()["smtp_host"] != "mail.attacker.example"

    # An Administrator's restore still carries it.
    by_admin = await client.post(
        "/api/site-settings/import",
        json={
            "sections": ["site_settings"],
            "payload": {**document, "data": {"site_settings": [{**row, "smtp_host": "smtp.example.com"}]}},
        },
        headers=_auth(admin),
    )
    assert by_admin.status_code == 200, by_admin.text
