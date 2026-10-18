"""Marketplace code-based install (#389 Slice B) — resolve → fetch → verify → apply.

Drives the whole pipeline against an httpx.MockTransport standing in for the
registry + CDN (no network), and asserts the trust boundary: a good signed pack
installs, a tampered or untrusted one is refused.
"""

import asyncio
import base64
import gzip
import io
import json
import time
import zipfile

import httpx
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import main
from db import SessionLocal
from models.theme_preset import ThemePreset
from routers import marketplace as marketplace_router
from routers.marketplace import get_registry_transport
from tests.conftest import admin_token
from utils import marketplace_registry as registry
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


async def test_install_needs_the_target_competition_to_be_visible(client):
    # install_content_pack is a global grant: a private competition it can't
    # see is refused before anything is fetched (GHSA-q472-m9qw-8gq4).
    from models.role import Role, RoleAssignment

    admin = await admin_token(client)
    private = (
        await client.post(
            "/api/competitions",
            json={"name": "Private", "visibility": "private"},
            headers=_auth(admin),
        )
    ).json()["id"]
    token = await _register(client, "installer@example.com")
    me = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]
    async with SessionLocal() as s:
        role = Role(name="Installer", scope="global", permissions=["install_content_pack"])
        s.add(role)
        await s.flush()
        s.add(RoleAssignment(user_id=me, competition_id=None, role_id=role.id))
        await s.commit()

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500)

    _use(httpx.MockTransport(handler))
    resp = await client.post(
        "/api/marketplace/install",
        json={"code": "8fy17", "competition_id": private},
        headers=_auth(token),
    )
    assert resp.status_code == 404, resp.text
    assert calls == []


# --- egress bounds (GHSA-r7rp-46pp-x55q) -------------------------------------
# The registry is trusted for content, not for size or pace: both calls stream
# with a byte cap and run under an overall deadline.


class _Drip:
    """An async byte stream that records how much the client pulled, so a test
    can assert the reader stopped at the cap rather than buffering it all."""

    def __init__(self, chunk: bytes, count: int, delay: float = 0.0):
        self.chunk, self.count, self.delay = chunk, count, delay
        self.pulled = 0

    async def __aiter__(self):
        for _ in range(self.count):
            if self.delay:
                await asyncio.sleep(self.delay)
            self.pulled += 1
            yield self.chunk


async def test_artifact_over_cap_by_content_length_is_refused_unread():
    body = _Drip(b"x" * 1024, 64)

    def handler(request: httpx.Request) -> httpx.Response:
        # Declares more than the cap; refused on the header, before any read.
        return httpx.Response(200, headers={"Content-Length": str(64 * 1024)}, content=body)

    with pytest.raises(registry.RegistryError, match="too large"):
        await registry.fetch_artifact(
            _ARTIFACT_URL, max_bytes=4096, transport=httpx.MockTransport(handler)
        )
    assert body.pulled == 0


async def test_endless_artifact_body_is_cut_off_at_the_cap():
    # Chunked (no Content-Length): only counting the bytes can stop it.
    body = _Drip(b"x" * 1024, 10_000)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))

    with pytest.raises(registry.RegistryError, match="too large"):
        await registry.fetch_artifact(_ARTIFACT_URL, max_bytes=4096, transport=transport)
    # Stopped one chunk past the 4 KiB cap — not after the 10 MB on offer.
    assert body.pulled == 5


async def test_artifact_within_cap_is_returned_whole():
    body = _Drip(b"ab", 3)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    assert (
        await registry.fetch_artifact(_ARTIFACT_URL, max_bytes=6, transport=transport)
        == b"ababab"
    )


async def test_resolve_response_over_its_cap_is_refused(monkeypatch):
    monkeypatch.setattr(registry, "_MAX_RESOLVE_BYTES", 4096)
    body = _Drip(b" " * 1024, 10_000)  # whitespace: valid JSON padding, endless
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))

    with pytest.raises(registry.RegistryError, match="too large"):
        await registry.resolve("https://registry.example", "8fy17", transport=transport)
    assert body.pulled == 5


async def test_slow_drip_artifact_hits_the_overall_deadline(monkeypatch):
    monkeypatch.setattr(registry, "_ARTIFACT_DEADLINE_S", 0.3)
    # Bytes keep arriving (so a per-read timeout never fires), well under the cap,
    # for ~3s in all — the deadline must end it, not the stream.
    body = _Drip(b"x", 60, delay=0.05)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))

    started = time.monotonic()
    with pytest.raises(registry.RegistryError, match="did not finish"):
        await registry.fetch_artifact(_ARTIFACT_URL, max_bytes=4096, transport=transport)
    assert time.monotonic() - started < 2.0


async def test_slow_drip_resolve_hits_the_overall_deadline(monkeypatch):
    monkeypatch.setattr(registry, "_RESOLVE_DEADLINE_S", 0.3)
    body = _Drip(b" ", 60, delay=0.05)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))

    started = time.monotonic()
    with pytest.raises(registry.RegistryError, match="did not answer"):
        await registry.resolve("https://registry.example", "8fy17", transport=transport)
    assert time.monotonic() - started < 2.0


async def test_oversized_artifact_is_refused_by_the_install_route(client, monkeypatch):
    token = await admin_token(client)
    pack = _theme_pack("toolarge")
    monkeypatch.setattr(marketplace_router, "MAX_ARTIFACT_BYTES", len(pack) - 1)
    _use(_transport(promised_digest=compute_digest(pack), served_bytes=pack))

    resp = await client.post("/api/marketplace/install", json={"code": "8fy17"}, headers=_auth(token))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "the artifact is too large"
    async with SessionLocal() as s:
        assert await s.get(ThemePreset, "toolarge") is None


# --- compressed bodies and malformed payloads (GHSA-r7rp-46pp-x55q) ----------


def _resolve_body(**overrides) -> dict:
    body = {
        "schema_version": 1,
        "code": "8fy17",
        "resolved": {"id": "reg.theme-pack", "name": "Registry Theme", "version": "1.0.0", "kind": "pack"},
        "publisher": {"id": "acme", "name": "ACME", "verified": True},
        "artifact": {"url": _ARTIFACT_URL, "digest": "sha256:" + "0" * 64},
        "requires_flagpost": {"min": "1.0.0"},
        "capabilities": [],
    }
    body.update(overrides)
    return body


def _serving(resolve_body: bytes, headers: dict | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/resolve/" in request.url.path:
            # Streamed, as off the network, so the raw-read path runs.
            return httpx.Response(200, headers=headers or {}, content=_Drip(resolve_body, 1))
        return httpx.Response(200, content=b"never fetched")

    return httpx.MockTransport(handler)


async def test_resolve_accepts_one_stored_gzip_layer():
    doc = json.dumps(_resolve_body()).encode()
    transport = _serving(gzip.compress(doc), {"Content-Encoding": "gzip"})
    resolved = await registry.resolve("https://registry.example", "8fy17", transport=transport)
    assert resolved.id == "reg.theme-pack"


async def test_resolve_refuses_a_stacked_encoding():
    doc = json.dumps(_resolve_body()).encode()
    transport = _serving(gzip.compress(gzip.compress(doc)), {"Content-Encoding": "gzip, gzip"})
    with pytest.raises(registry.RegistryError, match="refusing Content-Encoding"):
        await registry.resolve("https://registry.example", "8fy17", transport=transport)


async def test_deeply_nested_resolve_json_is_refused_not_a_crash():
    deep = b"[" * 100_000 + b"]" * 100_000  # inside the 256 KiB cap
    with pytest.raises(registry.RegistryError, match="nested too deeply"):
        await registry.resolve("https://registry.example", "8fy17", transport=_serving(deep))


async def test_a_nested_publisher_is_refused_by_the_resolve_route(client):
    # Nested past the response serializer's depth limit, which answers a 500.
    nested: object = "x"
    for _ in range(300):
        nested = [nested]
    token = await admin_token(client)
    body = _resolve_body(publisher={"id": "acme", "name": nested})
    _use(_serving(json.dumps(body).encode()))
    resp = await client.post("/api/marketplace/resolve", json={"code": "8fy17"}, headers=_auth(token))
    assert resp.status_code == 400, resp.text
    assert "publisher" in resp.json()["detail"]


@pytest.mark.parametrize(
    "url",
    [123, "http://cdn.example/\x00pack", "https://", "file:///etc/passwd"],
    ids=["not-a-string", "invalid", "no-host", "not-http"],
)
async def test_a_malformed_artifact_url_is_refused_by_the_install_route(client, url):
    token = await admin_token(client)
    body = _resolve_body(artifact={"url": url, "digest": "sha256:" + "0" * 64})
    _use(_serving(json.dumps(body).encode()))
    resp = await client.post("/api/marketplace/install", json={"code": "8fy17"}, headers=_auth(token))
    assert resp.status_code == 400, resp.text
    assert "artifact.url" in resp.json()["detail"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"resolved": {"id": "reg.theme-pack", "name": "bad \ud800", "version": "1.0.0", "kind": "pack"}},
        {"publisher": {"id": "acme", "name": "\udfff"}},
        {"publisher": {"id": "acme", "name": "ACME", "\ud800": True}},
        {"capabilities": ["network", "\ud800"]},
    ],
    ids=["resolved-field", "publisher-value", "publisher-key", "capability"],
)
async def test_a_lone_surrogate_is_refused_by_the_resolve_route(client, overrides):
    # JSON's \ud800 escape decodes to a lone surrogate, which the confirmation
    # response can't encode; it must be a 400, not a 500.
    token = await admin_token(client)
    _use(_serving(json.dumps(_resolve_body(**overrides)).encode()))
    resp = await client.post("/api/marketplace/resolve", json={"code": "8fy17"}, headers=_auth(token))
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"].startswith("malformed resolve response")
