"""Marketplace code-based install (#389 Slice B) — resolve → fetch → verify → apply.

Drives the whole pipeline against an httpx.MockTransport standing in for the
registry + CDN (no network), and asserts the trust boundary: a good signed pack
installs, a tampered or untrusted one is refused.
"""

import base64
import io
import json
import zipfile

import httpx
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import main
from db import SessionLocal
from models.theme_preset import ThemePreset
from routers.marketplace import get_registry_transport
from tests.conftest import admin_token
from utils.marketplace_verify import compute_digest
from utils.theme_tokens import THEME_TOKENS

_ARTIFACT_URL = "https://cdn.example/artifact.fpmod"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


def _theme_pack(theme_id: str = "registrytheme") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "plugin.yaml",
            yaml.safe_dump(
                {
                    "manifest_version": 2,
                    "id": "reg.theme-pack",
                    "name": "Registry Theme",
                    "version": "1.0.0",
                    "kind": "pack",
                    "pack": {"pack_type": "theme", "target": "site"},
                }
            ),
        )
        preset = {
            "id": theme_id,
            "name": "Registry",
            "mode": "dark",
            "tokens": {t: "#123456" for t in THEME_TOKENS},
        }
        zf.writestr("payload/themes.json", json.dumps([preset]))
    return buf.getvalue()


def _keypair() -> tuple[Ed25519PrivateKey, str]:
    priv = Ed25519PrivateKey.generate()
    raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return priv, base64.b64encode(raw).decode()


def _signature(priv: Ed25519PrivateKey, data: bytes, key_id: str = "k1") -> dict:
    return {"algorithm": "ed25519", "key_id": key_id, "value": base64.b64encode(priv.sign(data)).decode()}


def _transport(
    *, promised_digest: str, served_bytes: bytes, signature: dict | None = None, kind: str = "pack"
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/resolve/" in request.url.path:
            body = {
                "schema_version": 1,
                "code": request.url.path.rsplit("/", 1)[-1],
                "resolved": {
                    "id": "reg.theme-pack",
                    "name": "Registry Theme",
                    "version": "1.0.0",
                    "kind": kind,
                    "pack_type": "theme",
                },
                "publisher": {"id": "acme", "name": "ACME", "verified": True},
                "artifact": {"url": _ARTIFACT_URL, "digest": promised_digest},
                "requires_flagpost": {"min": "1.0.0"},
                "capabilities": [],
            }
            if signature is not None:
                body["signature"] = signature
            return httpx.Response(200, json=body)
        return httpx.Response(200, content=served_bytes)
    return httpx.MockTransport(handler)


def _use(transport: httpx.MockTransport) -> None:
    # The client fixture clears dependency_overrides on teardown, so no manual undo.
    main.app.dependency_overrides[get_registry_transport] = lambda: transport


async def _configure(client, token, **fields) -> None:
    resp = await client.put("/api/marketplace/settings", json=fields, headers=_auth(token))
    assert resp.status_code == 200, resp.text


async def test_install_signed_pack_from_code(client):
    token = await admin_token(client)
    priv, pub = _keypair()
    pack = _theme_pack("regtheme")
    await _configure(
        client, token, trust_policy="signed", trusted_keys=[{"key_id": "k1", "public_key": pub}]
    )
    _use(_transport(promised_digest=compute_digest(pack), served_bytes=pack, signature=_signature(priv, pack)))

    resp = await client.post("/api/marketplace/install", json={"code": "8fy17"}, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["installed"] == 1
    async with SessionLocal() as s:
        assert await s.get(ThemePreset, "regtheme") is not None


async def test_resolve_returns_confirmation(client):
    token = await admin_token(client)
    pack = _theme_pack()
    _use(_transport(promised_digest=compute_digest(pack), served_bytes=pack))
    resp = await client.post("/api/marketplace/resolve", json={"code": "8fy17"}, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == "reg.theme-pack"
    assert body["kind"] == "pack"
    assert body["installable"] is True
    assert body["signature_present"] is False


async def test_tampered_artifact_is_refused(client):
    token = await admin_token(client)
    priv, pub = _keypair()
    pack = _theme_pack("tampered")
    await _configure(
        client, token, trust_policy="signed", trusted_keys=[{"key_id": "k1", "public_key": pub}]
    )
    # Registry promises the real digest, but the CDN serves altered bytes.
    _use(_transport(promised_digest=compute_digest(pack), served_bytes=pack + b"x", signature=_signature(priv, pack)))
    resp = await client.post("/api/marketplace/install", json={"code": "8fy17"}, headers=_auth(token))
    assert resp.status_code == 400
    assert "verification failed" in resp.json()["detail"]
    async with SessionLocal() as s:
        assert await s.get(ThemePreset, "tampered") is None


async def test_untrusted_signature_is_refused(client):
    token = await admin_token(client)
    signer, _ = _keypair()          # signs the pack
    _, trusted_pub = _keypair()     # a different key is the only one we trust
    pack = _theme_pack("untrusted")
    await _configure(
        client, token, trust_policy="signed", trusted_keys=[{"key_id": "other", "public_key": trusted_pub}]
    )
    _use(_transport(promised_digest=compute_digest(pack), served_bytes=pack, signature=_signature(signer, pack)))
    resp = await client.post("/api/marketplace/install", json={"code": "8fy17"}, headers=_auth(token))
    assert resp.status_code == 400
    assert "verification failed" in resp.json()["detail"]


async def test_unsigned_refused_under_signed_policy(client):
    token = await admin_token(client)
    pack = _theme_pack("unsigned")
    await _configure(client, token, trust_policy="signed")
    _use(_transport(promised_digest=compute_digest(pack), served_bytes=pack))  # no signature
    resp = await client.post("/api/marketplace/install", json={"code": "8fy17"}, headers=_auth(token))
    assert resp.status_code == 400


async def test_marketplace_disabled_blocks_install(client):
    token = await admin_token(client)
    await _configure(client, token, enabled=False)
    resp = await client.post("/api/marketplace/install", json={"code": "8fy17"}, headers=_auth(token))
    assert resp.status_code == 404


async def test_install_requires_permission(client):
    participant = await _register(client, "nobody-install@example.com")
    resp = await client.post(
        "/api/marketplace/install", json={"code": "8fy17"}, headers=_auth(participant)
    )
    assert resp.status_code == 403


async def test_bad_code_rejected(client):
    token = await admin_token(client)
    resp = await client.post(
        "/api/marketplace/install", json={"code": "../etc/passwd"}, headers=_auth(token)
    )
    assert resp.status_code == 422
