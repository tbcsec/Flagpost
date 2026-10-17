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


async def test_direct_upload_blocked_when_marketplace_disabled(client):
    # #427 security-review M2: marketplace.enabled is a full kill switch, so the
    # direct content-pack upload path must refuse while the marketplace is off —
    # otherwise a locked-down instance could still install packs by file.
    token = await admin_token(client)
    await client.put(
        "/api/marketplace/settings", json={"enabled": False}, headers=_auth(token)
    )
    resp = await _install(client, token, _theme_pack([_theme_preset("locked")]))
    assert resp.status_code == 404
    assert "disabled" in resp.json()["detail"].lower()

    # Re-enabling restores the path.
    await client.put(
        "/api/marketplace/settings", json={"enabled": True}, headers=_auth(token)
    )
    assert (
        await _install(client, token, _theme_pack([_theme_preset("unlocked")]))
    ).status_code == 200


async def test_install_needs_the_target_competition_to_be_visible(client):
    # install_content_pack is a global grant: it installs into competitions the
    # holder can see, not into a private one by id (GHSA-q472-m9qw-8gq4).
    from models.role import Role, RoleAssignment

    admin = await admin_token(client)
    private = (
        await client.post(
            "/api/competitions",
            json={"name": "Private", "visibility": "private"},
            headers=_auth(admin),
        )
    ).json()["id"]
    public = (
        await client.post(
            "/api/competitions",
            json={"name": "Public", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]
    token = await _register(client, "packer@example.com")
    me = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]
    async with SessionLocal() as db:
        role = Role(name="Packer", scope="global", permissions=["install_content_pack"])
        db.add(role)
        await db.flush()
        db.add(RoleAssignment(user_id=me, competition_id=None, role_id=role.id))
        await db.commit()

    pack = _challenge_pack(
        [{"name": "Warmup", "category": "web", "description": "d", "value": 100, "flags": ["flag{a}"]}]
    )
    hidden = await _install(client, token, pack, private)
    assert hidden.status_code == 404, hidden.text
    async with SessionLocal() as s:
        assert (
            await s.scalar(select(Challenge).where(Challenge.competition_id == private))
        ) is None

    visible = await _install(client, token, pack, public)
    assert visible.status_code == 200, visible.text


# --- unpacking is bounded (GHSA-wvjv-56qv-9v42) -------------------------------


def _theme_pack_with(themes_json: bytes, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    manifest = {
        "manifest_version": 2, "id": "test.theme-pack", "name": "Theme Pack",
        "version": "1.0.0", "kind": "pack", "pack": {"pack_type": "theme", "target": "site"},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plugin.yaml", yaml.safe_dump(manifest))
        zf.writestr("payload/themes.json", themes_json, compress_type=compression)
    return buf.getvalue()


async def test_a_bzip2_or_lzma_member_is_refused(client):
    # Inflated whole on the first read whatever its header says — refused
    # before it's opened, even when its content is a perfectly good theme.
    token = await admin_token(client)
    themes = json.dumps([_theme_preset("squeezed")]).encode()
    for method in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
        resp = await _install(client, token, _theme_pack_with(themes, method))
        assert resp.status_code == 400, resp.text
        assert "isn't accepted" in resp.json()["detail"]
    async with SessionLocal() as s:
        assert await s.get(ThemePreset, "squeezed") is None


async def test_a_member_over_its_cap_is_refused(client):
    token = await admin_token(client)
    padded = json.dumps([_theme_preset("padded")]).encode() + b" " * (1024 * 1024)
    resp = await _install(client, token, _theme_pack_with(padded))
    assert resp.status_code == 400, resp.text
    assert "too large" in resp.json()["detail"]
    async with SessionLocal() as s:
        assert await s.get(ThemePreset, "padded") is None


async def test_the_entry_count_is_capped_before_parsing(client, monkeypatch):
    from utils import content_packs

    monkeypatch.setattr(content_packs, "MAX_PACK_MEMBERS", 1)
    token = await admin_token(client)
    resp = await _install(client, token, _theme_pack([_theme_preset("counted")]))
    assert resp.status_code == 400, resp.text
    assert "too many files" in resp.json()["detail"]


async def test_a_refused_challenge_bundle_is_a_pack_error(client, monkeypatch):
    # The ctfcli importer's own whole-bundle refusals surface as a 400, not a 500.
    from utils import challenge_yaml

    monkeypatch.setattr(challenge_yaml, "_MAX_MEMBERS", 0)
    token = await admin_token(client)
    comp_id = await _make_competition(client)
    pack = _challenge_pack([{"name": "Warmup", "value": 100, "flags": ["flag{a}"]}])
    resp = await _install(client, token, pack, comp_id)
    assert resp.status_code == 400, resp.text
    assert "too many files" in resp.json()["detail"]
