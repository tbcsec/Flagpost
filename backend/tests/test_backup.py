"""Platform export / import (ADR-0016): round-trip fidelity, additive skip-existing
import, restore-after-delete, and section selection + the endpoint auth gate."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from auth.security import generate_api_token, hash_api_token, hash_password
from db import SessionLocal, utcnow
from models.api_token import ApiToken
from models.challenge import Category, Challenge
from models.competition import Competition
from models.page import Page
from models.role import Role, RoleAssignment
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.submission import Submission
from models.user import User
from storage.memory import InMemoryStorage
from tests.conftest import admin_token
from utils import backup


async def _seed():
    """A competition with a category, a challenge, a user, and that user's solve."""
    async with SessionLocal() as db:
        comp = Competition(name="Export Test", description="d", participation_mode="individual",
                           visibility="public", invite_code="AAAA1111")
        db.add(comp)
        await db.flush()
        cat = Category(competition_id=comp.id, name="Web")
        db.add(cat)
        await db.flush()
        chal = Challenge(competition_id=comp.id, title="C1", description={},
                         category_id=cat.id, points=100, state="published",
                         flag_hash="abc", flag_salt="s")
        db.add(chal)
        user = User(email="player@example.com", display_name="player",
                    password_hash=hash_password("password123"))
        db.add(user)
        await db.flush()
        db.add(Submission(competition_id=comp.id, challenge_id=chal.id, user_id=user.id,
                          value="flag{x}", is_correct=True, points_awarded=100))
        await db.commit()
        return comp.id, chal.id, user.id


async def test_export_round_trip_and_additive_import(client):
    await _seed()
    await client.get("/api/site-settings")  # lazily materialise the singleton
    storage = InMemoryStorage()

    async with SessionLocal() as db:
        doc = await backup.export_data(db, storage, ["site_settings", "users", "competitions"])

    # The document carries the whole tree (site_settings has a deferred logo blob
    # — exporting it must not trigger an async lazy-load).
    assert doc["schema_version"] == backup.SCHEMA_VERSION
    assert len(doc["data"]["site_settings"]) == 1
    assert any(c["name"] == "Export Test" for c in doc["data"]["competitions"])
    assert any(c["title"] == "C1" for c in doc["data"]["challenges"])
    assert any(u["display_name"] == "player" for u in doc["data"]["users"])
    assert len(doc["data"]["submissions"]) == 1

    # Re-importing into the same install creates nothing (everything already
    # exists) and never duplicates — additive skip-existing.
    async with SessionLocal() as db:
        result = await backup.import_data(db, storage, doc, ["site_settings", "users", "competitions"])
    assert result["competitions"]["created"] == 0
    assert result["competitions"]["skipped"] == 1
    assert result["site_settings"]["created"] == 1  # singleton upsert
    async with SessionLocal() as db:
        comps = await db.scalar(select(func.count()).select_from(Competition).where(Competition.name == "Export Test"))
        assert comps == 1


async def test_restore_after_delete(client):
    comp_id, _, _ = await _seed()
    storage = InMemoryStorage()
    async with SessionLocal() as db:
        doc = await backup.export_data(db, storage, ["users", "competitions"])

    # Drop the competition (cascades to its challenge + submission); the user stays.
    async with SessionLocal() as db:
        await db.delete(await db.get(Competition, comp_id))
        await db.commit()

    async with SessionLocal() as db:
        result = await backup.import_data(db, storage, doc, ["users", "competitions"])
    assert result["competitions"]["created"] == 1

    # The whole tree came back under a fresh id, with the solve re-linked to the
    # (still-present, so skipped) user.
    async with SessionLocal() as db:
        comp = await db.scalar(select(Competition).where(Competition.name == "Export Test"))
        assert comp is not None and comp.id != comp_id
        chal = await db.scalar(select(Challenge).where(Challenge.competition_id == comp.id))
        assert chal is not None and chal.title == "C1"
        sub = await db.scalar(select(Submission).where(Submission.competition_id == comp.id))
        assert sub is not None and sub.is_correct is True
        # Exactly one user with that name — the import matched, didn't duplicate.
        users = await db.scalar(select(func.count()).select_from(User).where(User.display_name == "player"))
        assert users == 1


async def test_section_selection_limits_export(client):
    await _seed()
    storage = InMemoryStorage()
    async with SessionLocal() as db:
        doc = await backup.export_data(db, storage, ["users"])
    assert "users" in doc["data"]
    assert "competitions" not in doc["data"]
    assert doc["sections"] == ["users"]


async def test_api_tokens_never_leave_in_a_backup(client):
    """Personal API tokens (#75) are excluded like refresh_sessions.

    Only the SHA-256 is stored, but that hash is exactly what authentication
    compares against — exporting it would let the original raw token be
    re-armed on whatever install the document is imported into, bound to
    whichever local account matched by natural key.
    """
    _, _, user_id = await _seed()
    async with SessionLocal() as db:
        db.add(
            ApiToken(
                user_id=user_id,
                token_hash=hash_api_token(generate_api_token()),
                description="Should not be exported",
                expires_at=utcnow() + timedelta(days=30),
            )
        )
        await db.commit()

    storage = InMemoryStorage()
    async with SessionLocal() as db:
        doc = await backup.export_data(db, storage, ["users"])

    assert "api_tokens" not in doc["data"]
    # And no token hash leaks into the document by any other route.
    assert "Should not be exported" not in json.dumps(doc)


async def test_smtp_password_is_excluded_but_settings_still_round_trip(client):
    """ADR-0020 / #109: the SMTP password is encrypted with a per-install key,
    so it's dropped from the export (Spec.secret_columns) — but the rest of the
    site_settings row is portable and must survive."""
    admin = await admin_token(client)
    await client.put(
        "/api/site-settings/operational",
        json={
            "registration_open": True,
            "smtp_host": "smtp.example.com",
            "smtp_from": "ctf@example.com",
            "smtp_password": "do-not-export-me",
        },
        headers={"Authorization": f"Bearer {admin}"},
    )

    storage = InMemoryStorage()
    async with SessionLocal() as db:
        doc = await backup.export_data(db, storage, ["site_settings"])

    row = doc["data"]["site_settings"][0]
    # The secret is gone by name and by value — neither plaintext nor ciphertext.
    assert "smtp_password" not in row
    assert "do-not-export-me" not in json.dumps(doc)
    # ...but the portable fields on the same row are still there.
    assert row["smtp_host"] == "smtp.example.com"
    assert row["registration_open"] is True


async def test_import_cannot_clear_setup_completed_at(client):
    # F2: a crafted backup that nulls the one-way setup flag must NOT re-open the
    # unauthenticated first-run wizard. setup_completed_at is an immutable column
    # on import — its stored value survives regardless of the payload.
    storage = InMemoryStorage()
    async with SessionLocal() as db:
        stamped = await db.get(SiteSettings, SITE_SETTINGS_ID)
        assert stamped.setup_completed_at is not None  # client fixture provisions it
        doc = await backup.export_data(db, storage, ["site_settings"])

    # Attacker tampers the export to clear the flag.
    doc["data"]["site_settings"][0]["setup_completed_at"] = None
    async with SessionLocal() as db:
        await backup.import_data(db, storage, doc, ["site_settings"])

    async with SessionLocal() as db:
        row = await db.get(SiteSettings, SITE_SETTINGS_ID)
        assert row.setup_completed_at is not None  # preserved despite the null


async def test_import_rejects_foreign_document(client):
    async with SessionLocal() as db:
        with pytest.raises(backup.ImportError_):
            await backup.import_data(db, InMemoryStorage(), {"not": "ours"}, ["users"])
        with pytest.raises(backup.ImportError_):
            await backup.import_data(
                db, InMemoryStorage(),
                {"flagpost_export": True, "schema_version": 999, "data": {}},
                ["users"],
            )


async def test_export_requires_manage_site_settings(client):
    # A plain registered user can't export.
    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "nobody", "password": "password123"},
    )
    token = reg.json()["access_token"]
    resp = await client.post(
        "/api/site-settings/export",
        json={"sections": ["users"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_export_import_endpoints_round_trip(client):
    await _seed()
    admin = await admin_token(client)
    auth = {"Authorization": f"Bearer {admin}"}

    export = await client.post(
        "/api/site-settings/export",
        json={"sections": ["users", "competitions"]},
        headers=auth,
    )
    assert export.status_code == 200
    assert "attachment" in export.headers["content-disposition"]
    document = export.json()

    imported = await client.post(
        "/api/site-settings/import",
        json={"sections": ["users", "competitions"], "payload": document},
        headers=auth,
    )
    assert imported.status_code == 200
    # Nothing new — the data already exists (additive).
    assert imported.json()["competitions"]["created"] == 0


# --- Backup grant containment (backup escalation guard, review H1) ------------


async def _register(client, name):
    reg = await client.post(
        "/api/auth/register",
        json={"display_name": name, "password": "password123"},
    )
    return reg.json()["access_token"], reg.json()["user"]["id"]


async def _grant_global_role(user_id: str, name: str, perms: list[str]) -> str:
    async with SessionLocal() as db:
        role = Role(name=name, scope="global", permissions=perms)
        db.add(role)
        await db.flush()
        db.add(RoleAssignment(user_id=user_id, role_id=role.id, competition_id=None))
        await db.commit()
        return role.id


async def test_import_export_roles_users_sections_require_dedicated_grants(client):
    """Primary fix: a manage_site_settings-only delegate cannot read or write the
    roles/users sections — the path that let import mint a global Administrator."""
    token, uid = await _register(client, "sitedelegate")
    await _grant_global_role(uid, "Site delegate", ["manage_site_settings"])
    auth = {"Authorization": f"Bearer {token}"}
    payload = {"flagpost_export": True, "schema_version": backup.SCHEMA_VERSION, "data": {}}

    for section in ("roles", "users"):
        imp = await client.post(
            "/api/site-settings/import",
            json={"sections": [section], "payload": payload},
            headers=auth,
        )
        assert imp.status_code == 403, (section, imp.text)
        exp = await client.post(
            "/api/site-settings/export", json={"sections": [section]}, headers=auth
        )
        assert exp.status_code == 403, (section, exp.text)

    # A section they *are* entitled to still works (no over-broad block).
    ok = await client.post(
        "/api/site-settings/import",
        json={"sections": ["site_settings"], "payload": payload},
        headers=auth,
    )
    assert ok.status_code == 200, ok.text


async def test_import_cannot_grant_permissions_the_actor_lacks(client):
    """Defense-in-depth: even holding manage_roles, an import can't create a role
    carrying permissions beyond the actor's own global set (grant containment)."""
    token, uid = await _register(client, "roleadmin")
    await _grant_global_role(
        uid, "Role admin", ["manage_site_settings", "manage_roles", "manage_users"]
    )
    auth = {"Authorization": f"Bearer {token}"}
    payload = {
        "flagpost_export": True,
        "schema_version": backup.SCHEMA_VERSION,
        "data": {
            "roles": [
                {
                    "id": "src-role-1",
                    "name": "Imported power",
                    "description": "",
                    "is_system": False,
                    "scope": "global",
                    "permissions": ["edit_competition"],
                }
            ]
        },
    }
    imp = await client.post(
        "/api/site-settings/import",
        json={"sections": ["roles"], "payload": payload},
        headers=auth,
    )
    assert imp.status_code == 403, imp.text
    async with SessionLocal() as db:
        created = await db.scalar(
            select(func.count()).select_from(Role).where(Role.name == "Imported power")
        )
    assert created == 0


async def test_admin_import_of_roles_is_unaffected_by_containment(client):
    """A full Administrator holds the whole catalog, so containment never blocks
    a legitimate restore."""
    admin = await admin_token(client)
    auth = {"Authorization": f"Bearer {admin}"}
    payload = {
        "flagpost_export": True,
        "schema_version": backup.SCHEMA_VERSION,
        "data": {
            "roles": [
                {
                    "id": "src-role-2",
                    "name": "Imported power two",
                    "description": "",
                    "is_system": False,
                    "scope": "global",
                    "permissions": ["edit_competition"],
                }
            ]
        },
    }
    imp = await client.post(
        "/api/site-settings/import",
        json={"sections": ["roles"], "payload": payload},
        headers=auth,
    )
    assert imp.status_code == 200, imp.text
    assert imp.json()["roles"]["created"] == 1


async def test_custom_pages_round_trip(client):
    """Pages survive export/import (#198, ADR-0034).

    Site-level with no foreign keys, so the interesting parts are that the
    ProseMirror body comes back byte-identical (a JSON column, not text) and
    that `slug` acts as the natural key — a restore onto an install that already
    serves /p/about must leave that page alone rather than mint a second row
    that can never own the URL.
    """
    admin = await admin_token(client)
    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Sponsored by ACME"}]}
        ],
    }
    created = await client.post(
        "/api/admin/pages",
        json={
            "slug": "about",
            "title": "About",
            "content": doc,
            "icon": "info",
            "visibility": "public",
            "draft": False,
            "nav_order": 3,
        },
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert created.status_code == 201, created.text

    storage = InMemoryStorage()
    async with SessionLocal() as db:
        exported = await backup.export_data(db, storage, ["site_settings"])

    rows = exported["data"]["pages"]
    assert len(rows) == 1
    assert rows[0]["slug"] == "about"
    assert rows[0]["content"] == doc  # the document survives verbatim
    assert rows[0]["visibility"] == "public"
    assert rows[0]["nav_order"] == 3

    # Additive: re-importing finds the slug and skips rather than duplicating.
    async with SessionLocal() as db:
        result = await backup.import_data(db, storage, exported, ["site_settings"])
    assert result["pages"]["created"] == 0
    assert result["pages"]["skipped"] == 1

    async with SessionLocal() as db:
        count = await db.scalar(
            select(func.count()).select_from(Page).where(Page.slug == "about")
        )
        assert count == 1


async def test_pages_restore_after_deletion(client):
    """The other half of a backup's purpose: a deleted page comes back."""
    admin = await admin_token(client)
    auth = {"Authorization": f"Bearer {admin}"}
    created = (
        await client.post(
            "/api/admin/pages",
            json={"slug": "sponsors", "title": "Sponsors", "draft": False},
            headers=auth,
        )
    ).json()

    storage = InMemoryStorage()
    async with SessionLocal() as db:
        exported = await backup.export_data(db, storage, ["site_settings"])

    assert (
        await client.delete(f"/api/admin/pages/{created['id']}", headers=auth)
    ).status_code == 204

    async with SessionLocal() as db:
        result = await backup.import_data(db, storage, exported, ["site_settings"])
    assert result["pages"]["created"] == 1

    async with SessionLocal() as db:
        row = await db.scalar(select(Page).where(Page.slug == "sponsors"))
        assert row is not None and row.title == "Sponsors"
