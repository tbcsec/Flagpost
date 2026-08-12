"""Mass user import from CSV (#171): POST /api/users/import.

Covers the resolved decisions on the issue: preview-then-confirm (dry_run
writes nothing), create-only/non-destructive duplicates, data errors killing a
row while authorization limits only warn (account created, role skipped),
competition resolution by name only, and the bulk-op event shape (no per-row
``user.created``; ``role.assigned`` per grant; one ``users.imported`` summary).
"""

import io

from sqlalchemy import func, select

from db import SessionLocal
from models.role import Role, RoleAssignment
from models.user import User
from tests.conftest import admin_token
from utils.event_bus import event_bus


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _csv(*lines: str) -> dict:
    """Multipart payload for a CSV built from ``lines`` (header included)."""
    data = ("\n".join(lines) + "\n").encode()
    return {"file": ("users.csv", io.BytesIO(data), "text/csv")}


async def _import(client, token: str, *lines: str, dry_run: bool = False, data: dict | None = None):
    return await client.post(
        f"/api/users/import{'?dry_run=true' if dry_run else ''}",
        files=_csv(*lines),
        data=data or {},
        headers=_auth(token),
    )


async def _register(client, email: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _competition(client, admin: str, name: str = "CTF") -> str:
    return (
        await client.post(
            "/api/competitions",
            json={"name": name, "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _user_count() -> int:
    async with SessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(User))


async def _grant_global_role(user_id: str, name: str, perms: list[str]) -> None:
    async with SessionLocal() as db:
        role = Role(name=name, scope="global", permissions=perms)
        db.add(role)
        await db.flush()
        db.add(RoleAssignment(user_id=user_id, competition_id=None, role_id=role.id))
        await db.commit()


def _row(report: dict, line: int) -> dict:
    return next(r for r in report["rows"] if r["row"] == line)


# --- preview -----------------------------------------------------------------


async def test_dry_run_reports_and_writes_nothing(client):
    admin = await admin_token(client)
    before = await _user_count()

    resp = await _import(
        client,
        admin,
        "display_name,email,password",
        "alice,alice@example.com,supersecret1",
        "bob,,anothersecret2",
        dry_run=True,
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["dry_run"] is True
    assert (report["total"], report["created"], report["errors"]) == (2, 2, 0)
    assert {r["status"] for r in report["rows"]} == {"create"}

    assert await _user_count() == before  # preview never writes


# --- commit ------------------------------------------------------------------


async def test_commit_creates_working_accounts(client):
    admin = await admin_token(client)
    resp = await _import(
        client,
        admin,
        "display_name,email,password",
        "carol,carol@example.com,supersecret1",
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 1

    # The password was argon2-hashed and the account is live: login works.
    login = await client.post(
        "/api/auth/login", json={"identifier": "carol", "password": "supersecret1"}
    )
    assert login.status_code == 200

    # Admin-created accounts are pre-verified (#74), same as single create.
    async with SessionLocal() as db:
        carol = await db.scalar(select(User).where(User.display_name == "carol"))
        assert carol.email_verified_at is not None
        assert carol.is_active is True


async def test_duplicates_skip_in_file_and_against_directory(client):
    admin = await admin_token(client)
    await _register(client, "existing@example.com")  # display name "existing"

    resp = await _import(
        client,
        admin,
        "display_name,email,password",
        "EXISTING,,newpassword1",  # case-insensitive match on the directory
        "dave,dave@example.com,newpassword2",
        "Dave,other@example.com,newpassword3",  # dup of row 3 (name, case-folded)
        "eve,dave@example.com,newpassword4",  # dup of row 3 (email)
    )
    report = resp.json()
    assert report["created"] == 1 and report["skipped"] == 3
    assert _row(report, 2)["reason"] == "already exists"
    assert "row 3" in _row(report, 4)["reason"]
    assert "row 3" in _row(report, 5)["reason"]

    # Non-destructive: the existing account's password survived the re-import.
    login = await client.post(
        "/api/auth/login", json={"identifier": "existing", "password": "password123"}
    )
    assert login.status_code == 200


async def test_data_errors_kill_the_row_but_not_the_batch(client):
    admin = await admin_token(client)
    resp = await _import(
        client,
        admin,
        "display_name,email,password",
        "frank,frank@example.com,goodpassword1",
        ",missing@example.com,goodpassword2",  # no display_name
        "grace,not-an-email,goodpassword3",
        "heidi,heidi@example.com,short",
        f"{'x' * 121},long@example.com,goodpassword4",
    )
    report = resp.json()
    assert report["created"] == 1 and report["errors"] == 4
    assert _row(report, 2)["status"] == "create"
    assert "display_name is required" in _row(report, 3)["reason"]
    assert "invalid email" in _row(report, 4)["reason"]
    assert "8–256" in _row(report, 5)["reason"]
    assert "120" in _row(report, 6)["reason"]

    login = await client.post(
        "/api/auth/login", json={"identifier": "frank", "password": "goodpassword1"}
    )
    assert login.status_code == 200


# --- roles -------------------------------------------------------------------


async def test_role_assignment_by_name_and_default_competition(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin, "Spring CTF")

    resp = await _import(
        client,
        admin,
        "display_name,email,password,role,competition",
        "judy,judy@example.com,goodpassword1,judge,Spring CTF",  # case-insensitive role
        "mallory,,goodpassword2,Participant,",  # falls back to the default
        data={"default_competition_id": comp},
    )
    report = resp.json()
    assert resp.status_code == 200
    assert report["roles_assigned"] == 2
    assert _row(report, 2)["role"] == "Judge"  # canonical casing in the report

    async with SessionLocal() as db:
        judy = await db.scalar(select(User).where(User.display_name == "judy"))
        judge = await db.scalar(select(Role).where(Role.name == "Judge"))
        held = await db.scalar(
            select(RoleAssignment).where(
                RoleAssignment.user_id == judy.id,
                RoleAssignment.role_id == judge.id,
                RoleAssignment.competition_id == comp,
            )
        )
        assert held is not None


async def test_role_scope_and_resolution_errors(client):
    admin = await admin_token(client)
    await _competition(client, admin, "Dup Name")
    await _competition(client, admin, "Dup Name")  # competition names aren't unique

    resp = await _import(
        client,
        admin,
        "display_name,password,role,competition",
        "ivan,goodpassword1,Administrator,Dup Name",  # global role + competition
        "niaj,goodpassword2,Nonesuch,",  # unknown role
        "olivia,goodpassword3,Judge,Nowhere",  # unknown competition
        "peggy,goodpassword4,Judge,Dup Name",  # ambiguous competition
        "quentin,goodpassword5,Judge,",  # comp-scoped role, no comp, no default
    )
    report = resp.json()
    assert report["errors"] == 5 and report["created"] == 0
    assert "site-wide" in _row(report, 2)["reason"]
    assert "unknown role" in _row(report, 3)["reason"]
    assert "unknown competition" in _row(report, 4)["reason"]
    assert "ambiguous competition" in _row(report, 5)["reason"]
    assert "needs a competition" in _row(report, 6)["reason"]


async def test_global_role_assigns_site_wide(client):
    admin = await admin_token(client)
    resp = await _import(
        client,
        admin,
        "display_name,password,role",
        "rupert,goodpassword1,Administrator",
    )
    assert resp.json()["roles_assigned"] == 1
    async with SessionLocal() as db:
        rupert = await db.scalar(select(User).where(User.display_name == "rupert"))
        assignment = await db.scalar(
            select(RoleAssignment).where(RoleAssignment.user_id == rupert.id)
        )
        assert assignment is not None and assignment.competition_id is None


async def test_role_on_existing_account_is_assigned(client):
    """Create-only applies to the *account*; a role row still lands on it."""
    admin = await admin_token(client)
    comp = await _competition(client, admin, "Autumn CTF")
    _, uid = await _register(client, "sybil@example.com")

    resp = await _import(
        client,
        admin,
        "display_name,password,role,competition",
        "sybil,irrelevantpw1,Judge,Autumn CTF",
    )
    report = resp.json()
    assert report["created"] == 0 and report["skipped"] == 1
    assert report["roles_assigned"] == 1
    async with SessionLocal() as db:
        judge = await db.scalar(select(Role).where(Role.name == "Judge"))
        held = await db.scalar(
            select(RoleAssignment).where(
                RoleAssignment.user_id == uid,
                RoleAssignment.role_id == judge.id,
                RoleAssignment.competition_id == comp,
            )
        )
        assert held is not None

    # Idempotent re-run: the role half now skips too.
    again = (
        await _import(
            client,
            admin,
            "display_name,password,role,competition",
            "sybil,irrelevantpw1,Judge,Autumn CTF",
        )
    ).json()
    assert again["roles_assigned"] == 0 and again["roles_skipped"] == 1
    assert _row(again, 2)["role_reason"] == "already holds this role"


async def test_ungrantable_roles_warn_but_create_the_account(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin, "Winter CTF")

    # Actor 1: manage_users + view_all_users, but NOT manage_roles.
    token1, uid1 = await _register(client, "useradmin@example.com")
    await _grant_global_role(uid1, "User admin", ["manage_users", "view_all_users"])
    resp = await _import(
        client,
        token1,
        "display_name,password,role,competition",
        "trent,goodpassword1,Judge,Winter CTF",
    )
    report = resp.json()
    assert resp.status_code == 200
    assert report["created"] == 1 and report["roles_assigned"] == 0
    row = _row(report, 2)
    assert row["status"] == "create" and row["role_action"] == "skip"
    assert "manage_roles" in row["role_reason"]

    # Actor 2: manage_roles too, but Judge's permission set exceeds theirs —
    # the _assert_may_grant bound, downgraded to a warning (#171 decision 1).
    token2, uid2 = await _register(client, "roleadmin@example.com")
    await _grant_global_role(uid2, "Role admin", ["manage_users", "manage_roles"])
    resp = await _import(
        client,
        token2,
        "display_name,password,role,competition",
        "victor,goodpassword2,Judge,Winter CTF",
    )
    report = resp.json()
    assert report["created"] == 1 and report["roles_assigned"] == 0
    row = _row(report, 2)
    assert row["status"] == "create" and row["role_action"] == "skip"
    assert "exceeds your own permissions" in row["role_reason"]

    # Neither warned row produced an assignment.
    async with SessionLocal() as db:
        for name in ("trent", "victor"):
            subject = await db.scalar(select(User).where(User.display_name == name))
            assert subject is not None  # account exists…
            held = await db.scalar(
                select(RoleAssignment).where(RoleAssignment.user_id == subject.id)
            )
            assert held is None  # …with no role


# --- format edges ------------------------------------------------------------


async def test_name_alias_bom_and_ignored_columns(client):
    admin = await admin_token(client)
    data = "\ufeffname,password,affiliation\nwalter,goodpassword1,ACME Corp\n".encode()
    resp = await client.post(
        "/api/users/import",
        files={"file": ("ctfd.csv", io.BytesIO(data), "text/csv")},
        headers=_auth(admin),
    )
    report = resp.json()
    assert resp.status_code == 200
    assert report["created"] == 1
    assert report["ignored_columns"] == ["affiliation"]


async def test_missing_required_header_is_400(client):
    admin = await admin_token(client)
    resp = await _import(client, admin, "email,password", "a@example.com,goodpassword1")
    assert resp.status_code == 400
    assert "display_name" in resp.json()["detail"]


async def test_row_cap_is_413(client):
    from utils.user_import import MAX_IMPORT_ROWS

    admin = await admin_token(client)
    lines = ["display_name,password"] + [
        f"bulk{i},goodpassword{i}" for i in range(MAX_IMPORT_ROWS + 1)
    ]
    resp = await _import(client, admin, *lines, dry_run=True)
    assert resp.status_code == 413


async def test_max_rows_import_stays_under_a_timeout_budget(client):
    # The cap must stay honest: a *full-size* import has to complete well within
    # a 30 s client/proxy timeout, or we recreate the 500-user run's finding #1
    # (import succeeds server-side but the client times out). 200 rows ≈ 13 s of
    # argon2 at the measured rate; assert the cap is set conservatively.
    from utils.user_import import MAX_IMPORT_ROWS

    assert MAX_IMPORT_ROWS <= 300


async def test_unknown_default_competition_is_404(client):
    admin = await admin_token(client)
    resp = await _import(
        client,
        admin,
        "display_name,password",
        "xavier,goodpassword1",
        data={"default_competition_id": "nope"},
    )
    assert resp.status_code == 404


async def test_import_requires_manage_users(client):
    token, _ = await _register(client, "peon@example.com")
    resp = await _import(client, token, "display_name,password", "y,goodpassword1")
    assert resp.status_code == 403


# --- events ------------------------------------------------------------------


async def test_bulk_event_shape(client):
    """No per-row user.created; role.assigned per grant; one summary."""
    admin = await admin_token(client)
    comp = await _competition(client, admin, "Event CTF")

    captured: list[tuple[str, dict]] = []

    async def capture(event_name: str, payload: dict) -> None:
        captured.append((event_name, payload))

    for pattern in ("user.created", "role.assigned", "users.imported"):
        event_bus.subscribe(pattern, capture, owner="test-user-import")
    try:
        resp = await _import(
            client,
            admin,
            "display_name,password,role,competition",
            "zoe,goodpassword1,Judge,Event CTF",
            "yves,goodpassword2,,",
        )
        assert resp.status_code == 200
    finally:
        event_bus.unsubscribe_owner("test-user-import")

    names = [n for n, _ in captured]
    assert names.count("user.created") == 0
    assert names.count("role.assigned") == 1
    assert names.count("users.imported") == 1

    assigned = next(p for n, p in captured if n == "role.assigned")
    assert assigned["role_name"] == "Judge"
    assert assigned["competition_id"] == comp
    summary = next(p for n, p in captured if n == "users.imported")
    assert summary["created"] == 2 and summary["roles_assigned"] == 1


async def test_dry_run_emits_nothing(client):
    admin = await admin_token(client)
    captured: list[str] = []

    async def capture(event_name: str, payload: dict) -> None:
        captured.append(event_name)

    event_bus.subscribe("users.imported", capture, owner="test-user-import-dry")
    try:
        await _import(
            client, admin, "display_name,password", "quietuser,goodpassword1", dry_run=True
        )
    finally:
        event_bus.unsubscribe_owner("test-user-import-dry")
    assert captured == []
