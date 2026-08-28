"""Custom brand themes (#323, ADR-0011): the token validator, admin CRUD + its
guards, the active-theme embed in the public site-settings payload, the first-run
seed, and backup portability."""

import pytest
from sqlalchemy import select

from db import SessionLocal
from models.theme_preset import ThemePreset
from tests.conftest import admin_token
from utils.theme_seed import seed_builtin_themes
from utils.theme_tokens import THEME_TOKENS, ThemeValidationError, validate_theme_tokens

pytestmark = pytest.mark.asyncio


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _tokens(**over) -> dict:
    t = {k: "#101010" for k in THEME_TOKENS}
    t.update(over)
    return t


def _theme_body(**over) -> dict:
    body = {"id": "acme", "name": "Acme", "mode": "dark", "tokens": _tokens()}
    body.update(over)
    return body


async def _register(client, email="p@example.com") -> str:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return r.json()["access_token"]


# --- validator (unit) --------------------------------------------------------


async def test_validator_accepts_a_complete_pack():
    assert validate_theme_tokens(_tokens()) == _tokens()


async def test_validator_rejects_missing_unknown_bad_hex_and_injection():
    bad_payloads = [
        {k: "#101010" for k in list(THEME_TOKENS)[:-1]},  # missing one key
        _tokens(evil="#101010"),                          # unknown key
        _tokens(background="red"),                         # not hex
        _tokens(background="#10101"),                      # short hex
        _tokens(background="#101010;}"),                   # CSS-injection attempt
        _tokens(background="#10101g"),                     # non-hex char
    ]
    for bad in bad_payloads:
        with pytest.raises(ThemeValidationError):
            validate_theme_tokens(bad)


# --- admin CRUD + guards -----------------------------------------------------


async def test_theme_crud_lifecycle(client):
    admin = await admin_token(client)
    assert (await client.get("/api/admin/themes", headers=_auth(admin))).json() == []

    r = await client.post("/api/admin/themes", json=_theme_body(), headers=_auth(admin))
    assert r.status_code == 201, r.text
    assert r.json()["id"] == "acme" and r.json()["source"] == "custom"

    listing = (await client.get("/api/admin/themes", headers=_auth(admin))).json()
    assert [t["id"] for t in listing] == ["acme"]

    dup = await client.post("/api/admin/themes", json=_theme_body(), headers=_auth(admin))
    assert dup.status_code == 409

    upd = await client.put(
        "/api/admin/themes/acme",
        json={"name": "Acme Corp", "tokens": _tokens(primary="#ff00aa")},
        headers=_auth(admin),
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "Acme Corp"
    assert upd.json()["tokens"]["primary"] == "#ff00aa"

    assert (await client.delete("/api/admin/themes/acme", headers=_auth(admin))).status_code == 204
    assert (await client.get("/api/admin/themes", headers=_auth(admin))).json() == []


async def test_reserved_id_and_bad_payloads_are_rejected(client):
    admin = await admin_token(client)
    assert (await client.post("/api/admin/themes", json=_theme_body(id="harbor"), headers=_auth(admin))).status_code == 422
    assert (await client.post("/api/admin/themes", json=_theme_body(tokens=_tokens(background="nope")), headers=_auth(admin))).status_code == 422
    assert (await client.post("/api/admin/themes", json=_theme_body(mode="rainbow"), headers=_auth(admin))).status_code == 422


async def test_theme_routes_require_manage_site_settings(client):
    token = await _register(client)
    assert (await client.get("/api/admin/themes", headers=_auth(token))).status_code == 403
    assert (await client.post("/api/admin/themes", json=_theme_body(), headers=_auth(token))).status_code == 403
    assert (await client.delete("/api/admin/themes/x", headers=_auth(token))).status_code == 403


async def test_cannot_delete_the_active_theme(client):
    admin = await admin_token(client)
    await client.post("/api/admin/themes", json=_theme_body(id="live"), headers=_auth(admin))
    await client.put(
        "/api/site-settings",
        json={"platform_name": "X", "default_palette": "live", "accent": "signal"},
        headers=_auth(admin),
    )
    r = await client.delete("/api/admin/themes/live", headers=_auth(admin))
    assert r.status_code == 409 and "active" in r.json()["detail"].lower()


async def test_delete_missing_theme_is_404(client):
    admin = await admin_token(client)
    assert (await client.delete("/api/admin/themes/ghost", headers=_auth(admin))).status_code == 404


# --- active-theme embed in public site-settings ------------------------------


async def test_active_theme_embedded_when_default_names_a_preset(client):
    admin = await admin_token(client)
    await client.post(
        "/api/admin/themes",
        json=_theme_body(id="brandx", tokens=_tokens(background="#abcdef")),
        headers=_auth(admin),
    )
    await client.put(
        "/api/site-settings",
        json={"platform_name": "X", "default_palette": "brandx", "accent": "signal"},
        headers=_auth(admin),
    )
    pub = (await client.get("/api/site-settings")).json()
    assert pub["default_palette"] == "brandx"
    assert pub["active_theme"]["id"] == "brandx"
    assert pub["active_theme"]["mode"] == "dark"
    assert pub["active_theme"]["tokens"]["background"] == "#abcdef"


async def test_update_response_carries_the_active_theme(client):
    # Regression (#323): the admin PUT response must resolve active_theme too, not
    # just the public GET — the frontend caches the PUT response and the global
    # ThemeApplier reads it, so a save that dropped it reverted the whole site to
    # the default palette (only the appearance preview kept the custom theme).
    admin = await admin_token(client)
    await client.post(
        "/api/admin/themes",
        json=_theme_body(id="brandy", tokens=_tokens(primary="#ff0000")),
        headers=_auth(admin),
    )
    resp = await client.put(
        "/api/site-settings",
        json={"platform_name": "X", "default_palette": "brandy", "accent": "signal"},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active_theme"] is not None
    assert body["active_theme"]["id"] == "brandy"
    assert body["active_theme"]["tokens"]["primary"] == "#ff0000"


async def test_active_theme_is_null_for_a_builtin_palette(client):
    admin = await admin_token(client)
    await client.put(
        "/api/site-settings",
        json={"platform_name": "X", "default_palette": "eclipse", "accent": "signal"},
        headers=_auth(admin),
    )
    pub = (await client.get("/api/site-settings")).json()
    assert pub["default_palette"] == "eclipse"
    assert pub["active_theme"] is None


# --- seed --------------------------------------------------------------------


async def test_seed_builtin_themes_is_idempotent(client):
    async with SessionLocal() as db:
        assert await seed_builtin_themes(db) == 3
        assert await seed_builtin_themes(db) == 0  # no-op once populated
        ids = set((await db.scalars(select(ThemePreset.id))).all())
        assert {"corporate-blue", "midnight", "neon"} <= ids
        seeds = (await db.scalars(select(ThemePreset))).all()
        assert all(t.source == "builtin" for t in seeds)


# --- backup portability ------------------------------------------------------


async def test_theme_rides_the_backup(client):
    from storage.memory import InMemoryStorage
    from utils import backup

    admin = await admin_token(client)
    await client.post(
        "/api/admin/themes",
        json=_theme_body(id="portable", tokens=_tokens(primary="#123456")),
        headers=_auth(admin),
    )
    storage = InMemoryStorage()
    async with SessionLocal() as db:
        doc = await backup.export_data(db, storage, ["site_settings"])

    exported = doc["data"].get("theme_presets", [])
    assert any(t["id"] == "portable" for t in exported)
    # install-local authorship isn't portable and must not dangle a FK on import.
    assert all("created_by" not in t for t in exported)

    async with SessionLocal() as db:
        row = await db.get(ThemePreset, "portable")
        await db.delete(row)
        await db.commit()
    async with SessionLocal() as db:
        await backup.import_data(db, storage, doc, ["site_settings"])
    async with SessionLocal() as db:
        restored = await db.get(ThemePreset, "portable")
        assert restored is not None
        assert restored.tokens["primary"] == "#123456"
        assert restored.created_by is None


async def test_import_re_enforces_the_theme_token_boundary(client):
    """The backup import path must apply the same token/mode/reserved-id boundary
    the CRUD routes do (#323 review, HIGH). load_row does no content validation and
    ThemePreset.tokens is a generic JSON column, so a hand-crafted document could
    otherwise persist a non-#RRGGBB (or non-dict) token map, a bad mode, or a
    built-in-shadowing id — which, once named by default_palette, would 500 the
    *public* GET /api/site-settings paint every login screen depends on."""
    from storage.memory import InMemoryStorage
    from utils import backup

    storage = InMemoryStorage()

    def _doc(preset: dict) -> dict:
        return {
            "flagpost_export": True,
            "schema_version": backup.SCHEMA_VERSION,
            "sections": ["site_settings"],
            "data": {"theme_presets": [preset]},
        }

    bad_presets = [
        {"id": "evil", "name": "x", "mode": "dark", "tokens": "not-a-dict"},  # exploit A
        {"id": "evil", "name": "x", "mode": "dark", "tokens": _tokens(background=123)},
        {"id": "evil", "name": "x", "mode": "dark", "tokens": _tokens(background="red")},
        {"id": "evil", "name": "x", "mode": "dark", "tokens": {k: "#101010" for k in list(THEME_TOKENS)[:-1]}},
        {"id": "evil", "name": "x", "mode": "rainbow", "tokens": _tokens()},
        {"id": "harbor", "name": "x", "mode": "dark", "tokens": _tokens()},  # exploit B (reserved)
    ]
    for preset in bad_presets:
        async with SessionLocal() as db:
            with pytest.raises(backup.ImportError_):
                await backup.import_data(db, storage, _doc(preset), ["site_settings"])

    # The whole document is rejected atomically — nothing lands.
    async with SessionLocal() as db:
        assert (await db.scalars(select(ThemePreset.id))).all() == []

    # A well-formed preset still imports through the same path (happy path intact).
    async with SessionLocal() as db:
        await backup.import_data(
            db, storage, _doc(_theme_body(id="clean")), ["site_settings"]
        )
    async with SessionLocal() as db:
        assert await db.get(ThemePreset, "clean") is not None
