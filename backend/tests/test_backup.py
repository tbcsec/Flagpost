"""Platform export / import (ADR-0016): round-trip fidelity, additive skip-existing
import, restore-after-delete, and section selection + the endpoint auth gate."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from auth.permissions import PERMISSIONS_BY_KEY, Scope
from auth.security import generate_api_token, hash_api_token, hash_password
from db import SessionLocal, utcnow
from models.api_token import ApiToken
from models.audit_log import AuditLogEntry
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


async def test_challenge_deployment_rides_the_backup(client):
    """#320: a challenge's instancing deployment spec is authoring content that
    round-trips through export/import (ADR-0036 §5); instances never do."""
    from models.challenge_instancing import ChallengeDeployment

    async with SessionLocal() as db:
        comp = Competition(name="Inst Export", participation_mode="individual",
                           visibility="public", invite_code="INST0001")
        db.add(comp)
        await db.flush()
        chal = Challenge(competition_id=comp.id, title="Web", description={},
                         points=100, state="published")
        db.add(chal)
        await db.flush()
        db.add(ChallengeDeployment(
            competition_id=comp.id, challenge_id=chal.id, backend="docker",
            image_ref="ghcr.io/x/web:1", exposure="http", ports=[8080],
            env={"MODE": "hard"}, flag_mode="unique_per_instance",
            flag_template="flag{web-<random>}", per_subject_cap=2, lifetime_s=1800,
        ))
        await db.commit()
        comp_id = comp.id

    storage = InMemoryStorage()
    async with SessionLocal() as db:
        doc = await backup.export_data(db, storage, ["competitions"])
    assert any(d["image_ref"] == "ghcr.io/x/web:1" for d in doc["data"]["challenge_deployments"])

    # Delete the competition (cascades to the challenge + its deployment), then
    # re-import from the backup: the deployment comes back intact.
    async with SessionLocal() as db:
        await db.delete(await db.get(Competition, comp_id))
        await db.commit()
    async with SessionLocal() as db:
        result = await backup.import_data(db, storage, doc, ["competitions"])
    assert result["challenge_deployments"]["created"] == 1

    async with SessionLocal() as db:
        dep = await db.scalar(
            select(ChallengeDeployment).where(ChallengeDeployment.image_ref == "ghcr.io/x/web:1")
        )
    assert dep is not None
    assert dep.exposure == "http" and dep.ports == [8080] and dep.flag_mode == "unique_per_instance"
    assert dep.flag_template == "flag{web-<random>}" and dep.per_subject_cap == 2 and dep.lifetime_s == 1800
    # The imported deployment points at the freshly-imported challenge (FK remapped).
    async with SessionLocal() as db:
        chal = await db.get(Challenge, dep.challenge_id)
    assert chal is not None and chal.title == "Web"


async def test_backup_import_rejects_an_invalid_deployment_spec(client):
    """#320/#324: a hand-crafted backup with an internally-inconsistent deployment
    (tcp exposure, no ports) is rejected at import — load_row does no content
    validation, so the Spec's validate_row must repeat the authoring invariant."""
    async with SessionLocal() as db:
        comp = Competition(name="Bad Inst", participation_mode="individual",
                           visibility="public", invite_code="BADI0001")
        db.add(comp)
        await db.flush()
        chal = Challenge(competition_id=comp.id, title="C", description={}, points=10, state="published")
        db.add(chal)
        await db.commit()
        comp_id, chal_id = comp.id, chal.id

    import copy

    storage = InMemoryStorage()
    # Export the competition + challenge (no deployment yet), then delete it, so
    # each import below re-creates them in-transaction and the injected
    # deployment's challenge_id remap resolves before validate_row fires.
    async with SessionLocal() as db:
        full_doc = await backup.export_data(db, storage, ["competitions"])
    async with SessionLocal() as db:
        await db.delete(await db.get(Competition, comp_id))
        await db.commit()

    base = {
        "id": "dep-x", "competition_id": comp_id, "challenge_id": chal_id,
        "backend": "docker", "image_ref": "img:1", "exposure": "tcp", "ports": [1337],
        "env": {}, "manifest": None, "resource_limits": None, "lifetime_s": None,
        "per_subject_cap": 1, "flag_mode": "static", "flag_template": None,
    }
    bad_rows = [
        {**base, "exposure": "tcp", "ports": []},           # shape: tcp needs ports
        {**base, "ports": ["1337"]},                        # strict: string port (no coercion)
        {k: v for k, v in base.items() if k != "backend"},  # missing NOT-NULL backend
        {**base, "backend": "nonsense"},                    # unknown backend
    ]
    for bad in bad_rows:
        doc = copy.deepcopy(full_doc)
        doc["data"]["challenge_deployments"] = [bad]
        async with SessionLocal() as db:
            with pytest.raises(backup.ImportError_):
                await backup.import_data(db, storage, doc, ["competitions"])


async def test_backup_import_normalises_legacy_resource_limits(client):
    """GHSA-vgrr tightened the resource-limit bounds after v1.7.x. A deployment
    row an earlier release accepted must still restore — cleaned into today's
    bounds (what the provisioners would run anyway), not refused along with the
    whole backup. Values no provisioner can use (0 and fractions included) can
    never land as-is."""
    from models.challenge_instancing import ChallengeDeployment

    legacy = [
        ({"pids": 8}, {"pids": 16}),
        ({"memory_mb": 256.5}, {"memory_mb": 256}),
        ({"memory_mb": 256.0}, {"memory_mb": 256}),
        ({"cpu": 0.005}, {"cpu": 0.01}),
        ({"memory_mb": 8}, {"memory_mb": 16}),
        # int()-truncates to 0 (Docker's "unlimited") → floored; NaN and a bool
        # are no number at all → dropped, so the operator default applies.
        ({"cpu": float("nan"), "memory_mb": 0.5, "pids": True}, {"memory_mb": 16}),
    ]
    async with SessionLocal() as db:
        comp = Competition(name="Legacy Limits", participation_mode="individual",
                           visibility="public", invite_code="LEGL0001")
        db.add(comp)
        await db.flush()
        chals = [
            Challenge(competition_id=comp.id, title=f"L{i}", description={}, points=10,
                      state="published")
            for i in range(len(legacy))
        ]
        db.add_all(chals)
        await db.commit()
        comp_id, chal_ids = comp.id, [c.id for c in chals]

    storage = InMemoryStorage()
    async with SessionLocal() as db:
        doc = await backup.export_data(db, storage, ["competitions"])
    async with SessionLocal() as db:
        await db.delete(await db.get(Competition, comp_id))
        await db.commit()
    doc["data"]["challenge_deployments"] = [
        {
            "id": f"dep-{i}", "competition_id": comp_id, "challenge_id": chal_ids[i],
            "backend": "docker", "image_ref": "img:1", "exposure": "tcp", "ports": [1337],
            "env": {}, "manifest": None, "resource_limits": limits, "lifetime_s": None,
            "per_subject_cap": 1, "flag_mode": "static", "flag_template": None,
        }
        for i, (limits, _) in enumerate(legacy)
    ]
    async with SessionLocal() as db:
        result = await backup.import_data(db, storage, doc, ["competitions"])
    assert result["challenge_deployments"]["created"] == len(legacy)

    async with SessionLocal() as db:
        comp = await db.scalar(select(Competition).where(Competition.name == "Legacy Limits"))
        titles = {
            c.id: c.title
            for c in (await db.scalars(select(Challenge).where(Challenge.competition_id == comp.id))).all()
        }
        stored = {
            titles[d.challenge_id]: d.resource_limits
            for d in (await db.scalars(
                select(ChallengeDeployment).where(ChallengeDeployment.competition_id == comp.id)
            )).all()
        }
    for i, (_, want) in enumerate(legacy):
        got = stored[f"L{i}"]
        assert got == want, (i, got)
        # memory/pids land as ints, not merely equal floats.
        assert {k: type(v) for k, v in got.items()} == {k: type(v) for k, v in want.items()}


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


async def test_automations_section_requires_automation_create_grant(client):
    """GHSA-x8v4: a manage_site_settings-only delegate cannot import/export the
    automations section — that path let a delegate plant executable rules
    (webhook exfil, score tampering) it holds no automation grant for."""
    token, uid = await _register(client, "autodelegate")
    await _grant_global_role(uid, "Auto delegate", ["manage_site_settings"])
    auth = {"Authorization": f"Bearer {token}"}
    payload = {"flagpost_export": True, "schema_version": backup.SCHEMA_VERSION, "data": {}}

    imp = await client.post(
        "/api/site-settings/import",
        json={"sections": ["automations"], "payload": payload},
        headers=auth,
    )
    assert imp.status_code == 403, imp.text
    exp = await client.post(
        "/api/site-settings/export", json={"sections": ["automations"]}, headers=auth
    )
    assert exp.status_code == 403, exp.text


async def test_backup_import_rejects_a_malformed_automation_rule(client):
    """GHSA-x8v4: a crafted backup with an automation rule the visual builder
    would reject (unknown trigger, or an action with no valid type/config) is
    refused at import — load_row does no content validation, so the Spec's
    validate_row must repeat the RuleCreate invariant, or the engine would then
    execute arbitrary imported actions."""
    storage = InMemoryStorage()

    def _doc(rule):
        return {
            "flagpost_export": True,
            "schema_version": backup.SCHEMA_VERSION,
            "data": {"automation_rules": [rule]},
        }

    base = {
        "id": "rule-x", "competition_id": None, "owner_user_id": None,
        "name": "R", "trigger_type": "challenge.solved", "conditions": [],
        "actions": [{"type": "notify", "target": "role", "role_name": "Judge", "title": "hi"}],
        "is_enabled": True,
    }
    bad_rows = [
        {**base, "trigger_type": "not.a.real.event"},   # unknown trigger
        {**base, "actions": [{"type": "nonsense"}]},     # unknown action type
        {**base, "actions": [{"type": "webhook"}]},      # webhook missing url
    ]
    for bad in bad_rows:
        async with SessionLocal() as db:
            with pytest.raises(backup.ImportError_):
                await backup.import_data(db, storage, _doc(bad), ["automations"])


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


async def test_backup_import_rejects_a_malformed_page(client):
    """GHSA-4wrj: a crafted backup page that skips the authoring invariants — a
    bad slug, a disallowed visibility, a blank title — is refused at import, so a
    site-settings delegate can't publish an unvalidated public page."""
    storage = InMemoryStorage()

    def _doc(page):
        return {
            "flagpost_export": True,
            "schema_version": backup.SCHEMA_VERSION,
            "data": {"pages": [page]},
        }

    base = {
        "id": "page-x", "slug": "notice", "title": "T", "content": None,
        "visibility": "public", "draft": False,
    }
    bad_rows = [
        {**base, "slug": "a"},                 # too short / bad format
        {**base, "visibility": "everyone"},    # not an allowed visibility
        {**base, "title": "   "},              # blank title
    ]
    for bad in bad_rows:
        async with SessionLocal() as db:
            with pytest.raises(backup.ImportError_):
                await backup.import_data(db, storage, _doc(bad), ["site_settings"])


async def test_a_clarification_is_restored_against_its_challenge(client):
    """#450: a clarification's challenge_id is remapped to the restored
    challenge, like a ticket's."""
    from models.announcement import Announcement
    from models.ticket import Ticket, TicketMessage

    comp_id, chal_id, _ = await _seed()
    async with SessionLocal() as db:
        clar = Announcement(competition_id=comp_id, kind="clarification", challenge_id=chal_id,
                            title="C1", question="Negative numbers?", body="Yes.")
        db.add(clar)
        user = await db.scalar(select(User).where(User.display_name == "player"))
        ticket = Ticket(competition_id=comp_id, subject="Q", opener_user_id=user.id,
                        challenge_id=chal_id, kind="question")
        db.add(ticket)
        await db.flush()
        db.add(TicketMessage(competition_id=comp_id, ticket_id=ticket.id, author_user_id=user.id,
                             body="Yes.", sent_to_all=True, announcement_id=clar.id))
        db.add(Announcement(competition_id=comp_id, title="Hello", body="Welcome"))
        await db.commit()
    storage = InMemoryStorage()
    async with SessionLocal() as db:
        doc = await backup.export_data(db, storage, ["users", "competitions"])
    async with SessionLocal() as db:
        await db.delete(await db.get(Competition, comp_id))
        await db.commit()
    async with SessionLocal() as db:
        await backup.import_data(db, storage, doc, ["users", "competitions"])

    async with SessionLocal() as db:
        comp = await db.scalar(select(Competition).where(Competition.name == "Export Test"))
        chal = await db.scalar(select(Challenge).where(Challenge.competition_id == comp.id))
        rows = {a.title: a for a in (await db.scalars(
            select(Announcement).where(Announcement.competition_id == comp.id))).all()}
    assert rows["C1"].kind == "clarification" and rows["C1"].challenge_id == chal.id
    assert rows["C1"].question == "Negative numbers?"
    assert rows["Hello"].kind == "announcement" and rows["Hello"].challenge_id is None
    # The answer sent from a ticket still points at its (restored) clarification.
    async with SessionLocal() as db:
        msg = await db.scalar(select(TicketMessage).where(TicketMessage.sent_to_all.is_(True)))
    assert msg is not None and msg.announcement_id == rows["C1"].id


async def test_competitions_and_audit_log_sections_need_their_own_grants(client):
    """GHSA-3r5x: the competitions section carries every competition's content
    (flags, attachments, submissions, invite codes), and audit_log the whole
    event history — neither is site settings. A manage_site_settings delegate
    moves neither, and isn't offered them."""
    token, uid = await _register(client, "backupdelegate")
    await _grant_global_role(uid, "Backup delegate", ["manage_site_settings"])
    auth = {"Authorization": f"Bearer {token}"}
    payload = {"flagpost_export": True, "schema_version": backup.SCHEMA_VERSION, "data": {}}

    for section in ("competitions", "audit_log"):
        exp = await client.post(
            "/api/site-settings/export", json={"sections": [section]}, headers=auth
        )
        assert exp.status_code == 403, (section, exp.text)
        imp = await client.post(
            "/api/site-settings/import",
            json={"sections": [section], "payload": payload},
            headers=auth,
        )
        assert imp.status_code == 403, (section, imp.text)

    offered = await client.get("/api/site-settings/backup/sections", headers=auth)
    assert offered.json() == ["site_settings"]


async def test_audit_log_section_opens_for_view_audit_log(client):
    token, uid = await _register(client, "auditbackup")
    await _grant_global_role(uid, "Audit backup", ["manage_site_settings", "view_audit_log"])
    auth = {"Authorization": f"Bearer {token}"}
    exp = await client.post(
        "/api/site-settings/export", json={"sections": ["audit_log"]}, headers=auth
    )
    assert exp.status_code == 200, exp.text
    offered = await client.get("/api/site-settings/backup/sections", headers=auth)
    assert offered.json() == ["site_settings", "audit_log"]


async def test_competition_reach_alone_does_not_open_the_competitions_section(client):
    # A single competition-scope key held site-wide reaches every competition
    # (GHSA-q472) but isn't every competition's content: the section still
    # needs the whole competition catalog.
    token, uid = await _register(client, "reachbackup")
    await _grant_global_role(uid, "Reach backup", ["manage_site_settings", "ticket_view"])
    auth = {"Authorization": f"Bearer {token}"}
    exp = await client.post(
        "/api/site-settings/export", json={"sections": ["competitions"]}, headers=auth
    )
    assert exp.status_code == 403, exp.text


async def test_administrator_is_offered_every_section(client):
    admin = await admin_token(client)
    auth = {"Authorization": f"Bearer {admin}"}
    for query in ("", "?direction=export", "?direction=import"):
        offered = await client.get(f"/api/site-settings/backup/sections{query}", headers=auth)
        assert offered.json() == list(backup.SECTIONS), query


def _export_doc(data: dict) -> dict:
    return {"flagpost_export": True, "schema_version": backup.SCHEMA_VERSION, "data": data}


async def _offered(client, auth: dict, direction: str) -> list[str]:
    resp = await client.get(
        f"/api/site-settings/backup/sections?direction={direction}", headers=auth
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_users_export_needs_an_administrator(client):
    """GHSA-3r5x: the users section carries every account's password hash and
    email, Administrators' included, so exporting it is not a manage_users read.
    The import is additive (it never touches an existing account), so it stays
    on manage_users."""
    token, uid = await _register(client, "usersdelegate")
    await _grant_global_role(uid, "Users delegate", ["manage_site_settings", "manage_users"])
    auth = {"Authorization": f"Bearer {token}"}

    exp = await client.post(
        "/api/site-settings/export", json={"sections": ["users"]}, headers=auth
    )
    assert exp.status_code == 403, exp.text
    assert "users" not in await _offered(client, auth, "export")
    assert "users" in await _offered(client, auth, "import")

    row = {"id": "src-user-1", "display_name": "importeduser", "email": None,
           "password_hash": hash_password("password123")}
    imp = await client.post(
        "/api/site-settings/import",
        json={"sections": ["users"], "payload": _export_doc({"users": [row]})},
        headers=auth,
    )
    assert imp.status_code == 200, imp.text
    assert imp.json()["users"] == {"created": 1, "skipped": 0}

    admin = await admin_token(client)
    full = await client.post(
        "/api/site-settings/export",
        json={"sections": ["users"]},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert full.status_code == 200, full.text
    assert any(u["display_name"] == "importeduser" for u in full.json()["data"]["users"])


async def test_audit_log_import_needs_an_administrator(client):
    """GHSA-3r5x: view_audit_log reads the log; importing writes entries the log
    then presents as recorded history, so it needs the whole catalog."""
    token, uid = await _register(client, "auditimporter")
    await _grant_global_role(uid, "Audit importer", ["manage_site_settings", "view_audit_log"])
    auth = {"Authorization": f"Bearer {token}"}
    entry = {"id": "forged-entry-1", "event_name": "user.role_assigned",
             "payload": {"user_id": uid}, "competition_id": None, "user_id": uid}
    payload = _export_doc({"audit_log": [entry]})

    imp = await client.post(
        "/api/site-settings/import",
        json={"sections": ["audit_log"], "payload": payload},
        headers=auth,
    )
    assert imp.status_code == 403, imp.text
    async with SessionLocal() as db:
        assert await db.get(AuditLogEntry, "forged-entry-1") is None
    assert "audit_log" in await _offered(client, auth, "export")
    assert "audit_log" not in await _offered(client, auth, "import")

    admin = await admin_token(client)
    restored = await client.post(
        "/api/site-settings/import",
        json={"sections": ["audit_log"], "payload": payload},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["audit_log"]["created"] == 1


_COMPETITION_SCOPE = sorted(
    key for key, perm in PERMISSIONS_BY_KEY.items() if perm.scope is Scope.COMPETITION
)
_IMPORTED_COMPETITION = {
    "id": "src-comp-1", "name": "Imported comp", "description": "",
    "participation_mode": "individual", "visibility": "public", "invite_code": "SRC00001",
}


async def test_competitions_section_needs_create_competition(client):
    """GHSA-3r5x: importing the competitions section creates competitions, so
    every competition permission held site-wide isn't enough without the
    global create_competition grant."""
    token, uid = await _register(client, "nocreate")
    await _grant_global_role(
        uid, "No create", ["manage_site_settings", *_COMPETITION_SCOPE]
    )
    auth = {"Authorization": f"Bearer {token}"}

    imp = await client.post(
        "/api/site-settings/import",
        json={"sections": ["competitions"],
              "payload": _export_doc({"competitions": [_IMPORTED_COMPETITION]})},
        headers=auth,
    )
    assert imp.status_code == 403, imp.text
    async with SessionLocal() as db:
        assert await db.scalar(
            select(Competition).where(Competition.name == "Imported comp")
        ) is None
    exp = await client.post(
        "/api/site-settings/export", json={"sections": ["competitions"]}, headers=auth
    )
    assert exp.status_code == 403, exp.text
    for direction in ("export", "import"):
        assert "competitions" not in await _offered(client, auth, direction)


async def test_competitions_section_opens_short_of_administrator(client):
    """The other side of the gate: every competition permission plus
    create_competition opens the section both ways, without the rest of the
    catalog — it must not quietly demand an Administrator."""
    token, uid = await _register(client, "compbackup")
    await _grant_global_role(
        uid, "Competition backup",
        ["manage_site_settings", "create_competition", *_COMPETITION_SCOPE],
    )
    auth = {"Authorization": f"Bearer {token}"}

    for direction in ("export", "import"):
        assert "competitions" in await _offered(client, auth, direction)
    exp = await client.post(
        "/api/site-settings/export", json={"sections": ["competitions"]}, headers=auth
    )
    assert exp.status_code == 200, exp.text
    imp = await client.post(
        "/api/site-settings/import",
        json={"sections": ["competitions"],
              "payload": _export_doc({"competitions": [_IMPORTED_COMPETITION]})},
        headers=auth,
    )
    assert imp.status_code == 200, imp.text
    assert imp.json()["competitions"]["created"] == 1


async def test_pages_ride_site_settings_only_with_manage_pages(client):
    """GHSA-3r5x: pages travel in the site_settings section but are authored
    under manage_pages. Without it, the export leaves them out (drafts
    included) and the import skips them — counted, not silently dropped."""
    admin = await admin_token(client)
    created = await client.post(
        "/api/admin/pages",
        json={"slug": "secret-draft", "title": "Unreleased", "draft": True},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert created.status_code == 201, created.text

    token, uid = await _register(client, "settingsonly")
    await _grant_global_role(uid, "Settings only", ["manage_site_settings"])
    auth = {"Authorization": f"Bearer {token}"}

    exp = await client.post(
        "/api/site-settings/export", json={"sections": ["site_settings"]}, headers=auth
    )
    assert exp.status_code == 200, exp.text
    assert "pages" not in exp.json()["data"]
    assert "site_settings" in exp.json()["data"]

    page = {"id": "page-src", "slug": "planted", "title": "Planted", "content": None,
            "visibility": "public", "draft": False}
    imp = await client.post(
        "/api/site-settings/import",
        json={"sections": ["site_settings"], "payload": _export_doc({"pages": [page]})},
        headers=auth,
    )
    assert imp.status_code == 200, imp.text
    assert imp.json()["pages"] == {"created": 0, "skipped": 1}
    async with SessionLocal() as db:
        assert await db.scalar(select(Page).where(Page.slug == "planted")) is None

    # Holding manage_pages too, the delegate moves pages like an Administrator.
    token2, uid2 = await _register(client, "settingsandpages")
    await _grant_global_role(uid2, "Settings and pages", ["manage_site_settings", "manage_pages"])
    exp2 = await client.post(
        "/api/site-settings/export",
        json={"sections": ["site_settings"]},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert [p["slug"] for p in exp2.json()["data"]["pages"]] == ["secret-draft"]
