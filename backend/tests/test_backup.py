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
