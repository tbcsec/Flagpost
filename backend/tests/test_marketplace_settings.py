"""Marketplace settings surface (#389, ADR-0040): defaults, round-trip, validation, RBAC."""

import base64

from tests.conftest import admin_token

_VALID_KEY = base64.b64encode(b"\x01" * 32).decode()  # 32 bytes -> valid ed25519 length


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


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


async def test_get_returns_lazily_created_defaults(client):
    token = await admin_token(client)
    resp = await client.get("/api/marketplace/settings", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is True
    assert body["registry_url"] == "https://marketplace.flagpost.io"
    assert body["trust_policy"] == "verified"
    assert body["max_trust_tier"] == "declarative"
    assert body["trusted_keys"] == []


async def test_put_round_trips(client):
    token = await admin_token(client)
    resp = await client.put(
        "/api/marketplace/settings",
        json={
            "enabled": False,
            "registry_url": "https://mirror.example/registry",
            "trust_policy": "signed",
            "max_trust_tier": "code",
            "trusted_keys": [
                {"key_id": "acme-1", "public_key": _VALID_KEY, "verified": True, "label": "ACME"}
            ],
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is False
    assert body["registry_url"] == "https://mirror.example/registry"
    assert body["trust_policy"] == "signed"
    assert body["max_trust_tier"] == "code"
    assert body["trusted_keys"][0]["key_id"] == "acme-1"
    assert body["trusted_keys"][0]["verified"] is True
    # persisted
    again = await client.get("/api/marketplace/settings", headers=_auth(token))
    assert again.json()["trust_policy"] == "signed"


async def test_bad_trust_policy_rejected(client):
    token = await admin_token(client)
    resp = await client.put(
        "/api/marketplace/settings", json={"trust_policy": "bogus"}, headers=_auth(token)
    )
    assert resp.status_code == 422


async def test_sandboxed_tier_not_selectable(client):
    token = await admin_token(client)
    resp = await client.put(
        "/api/marketplace/settings", json={"max_trust_tier": "sandboxed"}, headers=_auth(token)
    )
    assert resp.status_code == 422


async def test_bad_trusted_key_rejected(client):
    token = await admin_token(client)
    resp = await client.put(
        "/api/marketplace/settings",
        json={"trusted_keys": [{"key_id": "x", "public_key": "not-valid-base64!!"}]},
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_non_http_registry_url_rejected(client):
    token = await admin_token(client)
    resp = await client.put(
        "/api/marketplace/settings", json={"registry_url": "ftp://evil"}, headers=_auth(token)
    )
    assert resp.status_code == 422


async def test_requires_manage_marketplace(client):
    participant = await _register(client, "nobody-mkt@example.com")
    assert (await client.get("/api/marketplace/settings", headers=_auth(participant))).status_code == 403
    put = await client.put(
        "/api/marketplace/settings", json={"enabled": False}, headers=_auth(participant)
    )
    assert put.status_code == 403
