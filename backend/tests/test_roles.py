"""Roles admin API (ARCHITECTURE.md §7.4): catalog, CRUD on custom roles,
system-role immutability, assignment scope rules, the last-admin guard, and that
a custom role's permissions actually gate a request end to end."""

from sqlalchemy import select

from models.audit_log import AuditLogEntry
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def _roles(client, admin: str) -> dict[str, dict]:
    resp = await client.get("/api/roles", headers=_auth(admin))
    assert resp.status_code == 200, resp.text
    return {r["name"]: r for r in resp.json()}


# --- RBAC + catalog --------------------------------------------------------


async def test_requires_manage_roles(client):
    outsider = await _register(client, "outsider@example.com")
    assert (await client.get("/api/roles")).status_code == 401
    assert (await client.get("/api/roles", headers=_auth(outsider))).status_code == 403


async def test_catalog_and_system_roles_present(client):
    admin = await admin_token(client)
    cat = (await client.get("/api/roles/catalog", headers=_auth(admin))).json()
    keys = {c["key"] for c in cat}
    assert {"manage_roles", "manage_site_settings", "challenge_view"} <= keys
    entry = next(c for c in cat if c["key"] == "manage_roles")
    assert entry["scope"] == "global" and entry["category"] == "Users & Roles"

    roles = await _roles(client, admin)
    assert {"Administrator", "Judge", "Participant"} <= set(roles)
    assert all(roles[n]["is_system"] for n in ("Administrator", "Judge", "Participant"))


# --- Create / clone / edit / delete ---------------------------------------


async def test_create_defaults_to_competition_scope_and_validates_keys(client):
    admin = await admin_token(client)
    bad = await client.post(
        "/api/roles",
        json={"name": "Bogus", "permissions": ["not_a_real_permission"]},
        headers=_auth(admin),
    )
    assert bad.status_code == 422

    resp = await client.post(
        "/api/roles",
        json={"name": "Challenge Author", "permissions": ["challenge_view", "challenge_create"]},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    role = resp.json()
    assert role["scope"] == "competition"  # §7.4 default
    assert role["is_system"] is False

    # Duplicate name is rejected.
    dup = await client.post(
        "/api/roles", json={"name": "Challenge Author"}, headers=_auth(admin)
    )
    assert dup.status_code == 409


async def test_clone_copies_source_permissions(client):
    admin = await admin_token(client)
    judge = (await _roles(client, admin))["Judge"]
    resp = await client.post(
        "/api/roles",
        json={"name": "Co-organiser", "clone_from": judge["id"]},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    clone = resp.json()
    assert clone["is_system"] is False
    assert set(clone["permissions"]) == set(judge["permissions"])
    assert clone["scope"] == judge["scope"]


async def test_system_roles_are_read_only(client):
    admin = await admin_token(client)
    judge = (await _roles(client, admin))["Judge"]
    edit = await client.patch(
        f"/api/roles/{judge['id']}", json={"permissions": []}, headers=_auth(admin)
    )
    assert edit.status_code == 409
    delete = await client.delete(f"/api/roles/{judge['id']}", headers=_auth(admin))
    assert delete.status_code == 409


async def test_edit_and_delete_custom_role(client):
    admin = await admin_token(client)
    created = (
        await client.post(
            "/api/roles",
            json={"name": "Observer", "permissions": ["challenge_view"]},
            headers=_auth(admin),
        )
    ).json()
    edited = await client.patch(
        f"/api/roles/{created['id']}",
        json={"description": "read-only", "permissions": ["challenge_view", "team_view_all"]},
        headers=_auth(admin),
    )
    assert edited.status_code == 200
    assert set(edited.json()["permissions"]) == {"challenge_view", "team_view_all"}

    deleted = await client.delete(f"/api/roles/{created['id']}", headers=_auth(admin))
    assert deleted.status_code == 204
    assert created["name"] not in await _roles(client, admin)


# --- Assignment ------------------------------------------------------------


async def _competition(client, admin: str) -> str:
    return (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "team"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def test_assignment_scope_rules(client):
    admin = await admin_token(client)
    await _register(client, "user@example.com")
    comp = await _competition(client, admin)
    roles = await _roles(client, admin)

    # A competition-scoped role needs a competition.
    r = await client.post(
        "/api/roles/assignments",
        json={"email": "user@example.com", "role_id": roles["Participant"]["id"]},
        headers=_auth(admin),
    )
    assert r.status_code == 400

    # A global role can't be pinned to a competition.
    r = await client.post(
        "/api/roles/assignments",
        json={"email": "user@example.com", "role_id": roles["Administrator"]["id"], "competition_id": comp},
        headers=_auth(admin),
    )
    assert r.status_code == 400

    # Unknown email → 404.
    r = await client.post(
        "/api/roles/assignments",
        json={"email": "ghost@example.com", "role_id": roles["Participant"]["id"], "competition_id": comp},
        headers=_auth(admin),
    )
    assert r.status_code == 404


async def test_custom_role_gates_a_request_end_to_end(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    user_token = await _register(client, "author@example.com")

    # Before any role: the user can't post an announcement in the competition.
    denied = await client.post(
        f"/api/competitions/{comp}/announcements",
        json={"title": "Hi", "body": "there"},
        headers=_auth(user_token),
    )
    assert denied.status_code == 403

    # Admin creates a custom role that can announce, and assigns it for this comp.
    role = (
        await client.post(
            "/api/roles",
            json={"name": "Announcer", "permissions": ["challenge_view", "announcement_create"]},
            headers=_auth(admin),
        )
    ).json()
    assigned = await client.post(
        "/api/roles/assignments",
        json={"email": "author@example.com", "role_id": role["id"], "competition_id": comp},
        headers=_auth(admin),
    )
    assert assigned.status_code == 201, assigned.text
    assert assigned.json()["role_name"] == "Announcer"
    assert assigned.json()["competition_name"] == "CTF"

    # Now the same request succeeds — the custom role's permission gates it.
    allowed = await client.post(
        f"/api/competitions/{comp}/announcements",
        json={"title": "Hi", "body": "there"},
        headers=_auth(user_token),
    )
    assert allowed.status_code == 201, allowed.text

    # Can't delete a role that's still assigned.
    blocked = await client.delete(f"/api/roles/{role['id']}", headers=_auth(admin))
    assert blocked.status_code == 409

    # Unassign, then delete works.
    aid = assigned.json()["id"]
    assert (await client.delete(f"/api/roles/assignments/{aid}", headers=_auth(admin))).status_code == 204
    assert (await client.delete(f"/api/roles/{role['id']}", headers=_auth(admin))).status_code == 204


async def test_cannot_remove_last_administrator(client):
    admin = await admin_token(client)
    roles = await _roles(client, admin)
    admin_role_id = roles["Administrator"]["id"]
    assignments = (
        await client.get(f"/api/roles/assignments?role_id={admin_role_id}", headers=_auth(admin))
    ).json()
    assert len(assignments) == 1
    resp = await client.delete(
        f"/api/roles/assignments/{assignments[0]['id']}", headers=_auth(admin)
    )
    assert resp.status_code == 409


async def test_banned_administrator_does_not_satisfy_the_last_admin_guard(client):
    """Regression: the guard counted assignment rows, not *active* holders.

    Banning a user clears `is_active` but leaves the role assignment, so with a
    banned second administrator the count read 2 and the guard let the only
    remaining active administrator drop their own role. Active administrators
    then hit zero, which reopened the public setup wizard on a live install and
    let any anonymous caller mint a new owner.
    """
    admin = await admin_token(client)
    roles = await _roles(client, admin)
    admin_role_id = roles["Administrator"]["id"]

    # A second administrator, who is then banned.
    second = await client.post(
        "/api/users",
        json={"display_name": "second-admin", "password": "s3cretpw!"},
        headers=_auth(admin),
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    assigned = await client.post(
        "/api/roles/assignments",
        json={"email": "second-admin", "role_id": admin_role_id, "competition_id": None},
        headers=_auth(admin),
    )
    assert assigned.status_code == 201, assigned.text
    assert (
        await client.post(f"/api/users/{second_id}/ban", headers=_auth(admin))
    ).status_code == 200

    # Two Administrator assignment rows now exist, but only one active holder.
    assignments = (
        await client.get(
            f"/api/roles/assignments?role_id={admin_role_id}", headers=_auth(admin)
        )
    ).json()
    assert len(assignments) == 2

    # Removing the *active* administrator's assignment must still be refused.
    mine = next(a for a in assignments if a["user_id"] != second_id)
    resp = await client.delete(
        f"/api/roles/assignments/{mine['id']}", headers=_auth(admin)
    )
    assert resp.status_code == 409, resp.text

    # The install therefore still has an owner, and stays un-claimable.
    assert (await client.get("/api/setup/status")).json()["needs_setup"] is False


async def _role_manager(client, admin: str) -> str:
    """A user holding a global role with `manage_roles` and nothing else.

    Exactly what the router's docstring advertises: "hand out narrower access
    than the three built-ins".
    """
    role = await client.post(
        "/api/roles",
        json={"name": "Role Manager", "scope": "global", "permissions": ["manage_roles"]},
        headers=_auth(admin),
    )
    assert role.status_code == 201, role.text
    token = await _register(client, "rolemgr@example.com")
    assigned = await client.post(
        "/api/roles/assignments",
        json={
            "email": "rolemgr@example.com",
            "role_id": role.json()["id"],
            "competition_id": None,
        },
        headers=_auth(admin),
    )
    assert assigned.status_code == 201, assigned.text
    return token


async def test_role_manager_cannot_self_assign_administrator(client):
    """Regression: `manage_roles` must not be a route to full Administrator.

    `GET /api/roles` is permitted by `manage_roles` and returns the built-in
    Administrator's id, and `assign_role` never asked whether the actor was
    entitled to confer it — so this was two requests to all 38 permissions.
    """
    admin = await admin_token(client)
    manager = await _role_manager(client, admin)

    admin_role_id = (await _roles(client, manager))["Administrator"]["id"]
    resp = await client.post(
        "/api/roles/assignments",
        json={
            "email": "rolemgr@example.com",
            "role_id": admin_role_id,
            "competition_id": None,
        },
        headers=_auth(manager),
    )
    assert resp.status_code == 403, resp.text

    # And they genuinely didn't gain the permissions.
    assert (
        await client.get("/api/users", headers=_auth(manager))
    ).status_code == 403


async def test_role_manager_cannot_mint_a_role_beyond_their_own_permissions(client):
    """The equivalent longer route: create the power, then take it."""
    admin = await admin_token(client)
    manager = await _role_manager(client, admin)

    resp = await client.post(
        "/api/roles",
        json={
            "name": "Definitely Not Admin",
            "scope": "global",
            "permissions": ["manage_roles", "manage_users", "manage_site_settings"],
        },
        headers=_auth(manager),
    )
    assert resp.status_code == 403, resp.text
    assert "manage_users" in resp.json()["detail"]

    # Cloning Administrator is the same escalation wearing a hat.
    admin_role_id = (await _roles(client, manager))["Administrator"]["id"]
    cloned = await client.post(
        "/api/roles",
        json={"name": "Admin Copy", "clone_from": admin_role_id},
        headers=_auth(manager),
    )
    assert cloned.status_code == 403, cloned.text


async def test_role_manager_can_still_manage_within_its_own_grant(client):
    """The fix must not break the delegation it protects."""
    admin = await admin_token(client)
    manager = await _role_manager(client, admin)

    created = await client.post(
        "/api/roles",
        json={"name": "Deputy", "scope": "global", "permissions": ["manage_roles"]},
        headers=_auth(manager),
    )
    assert created.status_code == 201, created.text

    # Renaming touches no permissions, so it stays allowed...
    renamed = await client.patch(
        f"/api/roles/{created.json()['id']}",
        json={"description": "a deputy"},
        headers=_auth(manager),
    )
    assert renamed.status_code == 200, renamed.text

    # ...as does dropping a permission, which is a de-escalation.
    stripped = await client.patch(
        f"/api/roles/{created.json()['id']}",
        json={"permissions": []},
        headers=_auth(manager),
    )
    assert stripped.status_code == 200, stripped.text


async def test_role_mutations_emit_events(client):
    admin = await admin_token(client)
    role = (
        await client.post(
            "/api/roles", json={"name": "Ephemeral", "permissions": []}, headers=_auth(admin)
        )
    ).json()
    await client.patch(
        f"/api/roles/{role['id']}", json={"description": "x"}, headers=_auth(admin)
    )
    from db import SessionLocal

    async with SessionLocal() as session:
        names = set(
            (
                await session.execute(
                    select(AuditLogEntry.event_name).where(
                        AuditLogEntry.event_name.like("role.%")
                    )
                )
            ).scalars().all()
        )
    assert {"role.created", "role.updated"} <= names
