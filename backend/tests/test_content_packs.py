"""Content-pack install (Tier 0 marketplace, #387, ADR-0040).

Exercises the whole path — module mount, permission gate, manifest validation,
and the per-type importers — and asserts the two load-bearing properties:
validation is NOT bypassed (a bad theme token / wrong kind is refused), and a
bulk install emits ONE platform event, not a per-row challenge.created flood.
"""

import io
import json
import zipfile

import yaml
from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from models.challenge import Challenge
from models.theme_preset import ThemePreset
from tests.conftest import admin_token
from utils.theme_tokens import THEME_TOKENS


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_competition(client) -> str:
    token = await admin_token(client)
    resp = await client.post(
        "/api/competitions", json={"name": "CTF"}, headers=_auth(token)
    )
    return resp.json()["id"]


async def _register(client, email) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": email.split("@")[0],
        },
    )
    return resp.json()["access_token"]


def _full_tokens(color: str = "#123456") -> dict:
    return {t: color for t in THEME_TOKENS}


def _pack(manifest: dict, members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plugin.yaml", yaml.safe_dump(manifest))
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _theme_preset(id_: str = "oceanic") -> dict:
    return {"id": id_, "name": "Oceanic", "mode": "dark", "tokens": _full_tokens()}


def _theme_pack(presets: list[dict], **manifest_over) -> bytes:
    manifest = {
        "manifest_version": 2,
        "id": "test.theme-pack",
        "name": "Theme Pack",
        "version": "1.0.0",
        "kind": "pack",
        "pack": {"pack_type": "theme", "target": "site"},
    }
    manifest.update(manifest_over)
    return _pack(manifest, {"payload/themes.json": json.dumps(presets).encode()})


def _ctfcli_zip(specs: list[dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, spec in enumerate(specs):
            slug = str(spec.get("name", f"c{i}")).lower().replace(" ", "-")
            zf.writestr(f"{slug}/challenge.yml", yaml.safe_dump(spec))
    return buf.getvalue()


def _challenge_pack(specs: list[dict], **manifest_over) -> bytes:
    manifest = {
        "manifest_version": 2,
        "id": "test.chal-pack",
        "name": "Chal Pack",
        "version": "1.0.0",
        "kind": "pack",
        "pack": {"pack_type": "challenges", "target": "competition"},
    }
    manifest.update(manifest_over)
    return _pack(manifest, {"payload/challenges.zip": _ctfcli_zip(specs)})


async def _install(client, token, pack: bytes, competition_id: str | None = None):
    data = {"competition_id": competition_id} if competition_id else None
    return await client.post(
        "/api/content-packs/install",
        files={"file": ("pack.zip", pack, "application/zip")},
        data=data,
        headers=_auth(token),
    )


# --- happy paths ------------------------------------------------------------


async def test_install_theme_pack(client):
    token = await admin_token(client)
    resp = await _install(client, token, _theme_pack([_theme_preset("oceanic")]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pack_type"] == "theme"
    assert body["target"] == "site"
    assert body["result"]["installed"] == 1
    async with SessionLocal() as s:
        theme = await s.get(ThemePreset, "oceanic")
    assert theme is not None and theme.mode == "dark"
    assert theme.tokens["primary"] == "#123456"


async def test_install_challenge_pack(client):
    token = await admin_token(client)
    comp_id = await _make_competition(client)
    pack = _challenge_pack(
        [
            {
                "name": "Warmup",
                "category": "web",
                "description": "d",
                "value": 100,
                "state": "visible",
                "flags": ["flag{a}"],
            }
        ]
    )
    resp = await _install(client, token, pack, comp_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pack_type"] == "challenges"
    assert body["target"] == comp_id
    assert body["result"]["created"] == 1
    async with SessionLocal() as s:
        ch = await s.scalar(
            select(Challenge).where(
                Challenge.competition_id == comp_id, Challenge.title == "Warmup"
            )
        )
    assert ch is not None and ch.points == 100


# --- validation is not bypassed ---------------------------------------------


async def test_theme_pack_bad_token_rejected(client):
    token = await admin_token(client)
    bad = _theme_preset("badtheme")
    bad["tokens"]["primary"] = "not-a-hex"
    resp = await _install(client, token, _theme_pack([bad]))
    assert resp.status_code == 400
    async with SessionLocal() as s:
        assert await s.get(ThemePreset, "badtheme") is None  # atomic — nothing landed


async def test_not_a_content_pack_rejected(client):
    token = await admin_token(client)
    module_manifest = _pack(
        {
            "manifest_version": 2,
            "id": "x.mod",
            "name": "Mod",
            "version": "1.0.0",
            "kind": "module",
            "trust_tier": "code",
        },
        {},
    )
    resp = await _install(client, token, module_manifest)
    assert resp.status_code == 400
    assert "content pack" in resp.json()["detail"]


async def test_challenge_pack_requires_competition(client):
    token = await admin_token(client)
    pack = _challenge_pack(
        [{"name": "X", "category": "web", "value": 50, "state": "visible", "flags": ["flag{x}"]}]
    )
    resp = await _install(client, token, pack)  # no competition_id
    assert resp.status_code == 400
    assert "competition" in resp.json()["detail"].lower()


async def test_version_incompatible_rejected(client):
    token = await admin_token(client)
    pack = _theme_pack([_theme_preset("futuretheme")], requires_flagpost={"min": "99.0.0"})
    resp = await _install(client, token, pack)
    assert resp.status_code == 400
    assert "99.0.0" in resp.json()["detail"]
    async with SessionLocal() as s:
        assert await s.get(ThemePreset, "futuretheme") is None


async def test_unsupported_pack_type_rejected(client):
    token = await admin_token(client)
    pack = _pack(
        {
            "manifest_version": 2,
            "id": "x.tr",
            "name": "Tr",
            "version": "1.0.0",
            "kind": "pack",
            "pack": {"pack_type": "translations"},
        },
        {"payload/messages.json": b"{}"},
    )
    resp = await _install(client, token, pack)
    assert resp.status_code == 400
    assert "not supported" in resp.json()["detail"]


# --- authorization + event hygiene ------------------------------------------


async def test_install_requires_permission(client):
    participant = await _register(client, "nobody@example.com")
    resp = await _install(client, participant, _theme_pack([_theme_preset("nope")]))
    assert resp.status_code == 403


async def test_challenge_pack_emits_one_bulk_event_not_per_row(client):
    token = await admin_token(client)
    comp_id = await _make_competition(client)
    pack = _challenge_pack(
        [
            {"name": "A", "category": "web", "value": 100, "state": "visible", "flags": ["flag{a}"]},
            {"name": "B", "category": "web", "value": 200, "state": "visible", "flags": ["flag{b}"]},
        ]
    )
    resp = await _install(client, token, pack, comp_id)
    assert resp.status_code == 200, resp.text
    async with SessionLocal() as s:
        installed = (
            await s.scalars(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "platform.content_pack_installed"
                )
            )
        ).all()
        per_row = (
            await s.scalars(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "challenge.created"
                )
            )
        ).all()
    assert len(installed) == 1
    assert per_row == []  # bulk import must not flood per-challenge events
