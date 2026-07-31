"""OIDC login (#58, ADR-0021).

Runs the real flow against a stubbed IdP: a genuine RSA keypair signs the ID
tokens, and the discovery/JWKS/token endpoints are monkeypatched at the
``utils.oidc`` seam. That keeps the signature validation under test rather than
mocked away — the point of most of these cases is that a *bad* token is
rejected, which is meaningless if nothing verifies signatures.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select, text

from db import SessionLocal
from models.oidc import OidcProvider, UserExternalIdentity
from models.role import RoleAssignment
from models.user import User
from tests.conftest import admin_token

ISSUER = "https://idp.example.com"
CLIENT_ID = "flagpost-test-client"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(
    encoding=__import__("cryptography.hazmat.primitives.serialization", fromlist=["x"]).Encoding.PEM,
    format=__import__("cryptography.hazmat.primitives.serialization", fromlist=["x"]).PrivateFormat.PKCS8,
    encryption_algorithm=__import__("cryptography.hazmat.primitives.serialization", fromlist=["x"]).NoEncryption(),
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _discovery() -> dict:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks",
        "userinfo_endpoint": f"{ISSUER}/userinfo",
    }


def _id_token(*, nonce: str, sub="idp-subject-1", email="sso@example.com",
              email_verified=True, aud=CLIENT_ID, issuer=ISSUER, key=None,
              extra=None) -> str:
    now = int(time.time())
    claims = {
        "iss": issuer,
        "sub": sub,
        "aud": aud,
        "exp": now + 300,
        "iat": now,
        "nonce": nonce,
        "email": email,
        "email_verified": email_verified,
        **(extra or {}),
    }
    return jwt.encode(claims, key or _PRIVATE_PEM, algorithm="RS256")


@pytest.fixture
def idp(monkeypatch):
    """Stub the provider's network surface, capturing the nonce the login step
    minted so the fake ID token can echo it back."""
    from utils import oidc as oidc_utils

    state = {"nonce": None, "token_response": None, "userinfo": {}}

    async def _discover(issuer):
        return _discovery()

    async def _exchange(**kwargs):
        if state["token_response"] is not None:
            return state["token_response"]
        return {
            "id_token": _id_token(nonce=state["nonce"]),
            "access_token": "stub-access-token",
        }

    async def _userinfo(document, access_token):
        return state["userinfo"]

    # Real validate_id_token runs — only the key fetch is stubbed, so signature,
    # iss, aud, exp and nonce are all genuinely checked.
    async def _signing_key(jwks_uri, token):
        return _KEY.public_key()

    monkeypatch.setattr(oidc_utils, "discover", _discover)
    monkeypatch.setattr(oidc_utils, "exchange_code", _exchange)
    monkeypatch.setattr(oidc_utils, "fetch_userinfo", _userinfo)
    monkeypatch.setattr(oidc_utils, "_signing_key", _signing_key)
    monkeypatch.setattr(oidc_utils, "validate_issuer_url", lambda url: _noop())
    return state


async def _noop():
    return None


async def _create_provider(client, admin, *, enabled=True, slug="testidp") -> dict:
    resp = await client.post(
        "/api/admin/oidc-providers",
        json={
            "name": "Test IdP",
            "slug": slug,
            "issuer": ISSUER,
            "client_id": CLIENT_ID,
            "client_secret": "super-secret-value",
            "enabled": enabled,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _begin_login(client, idp, slug="testidp"):
    """Hit /login, capture the state + nonce the server minted."""
    resp = await client.get(f"/api/auth/oidc/{slug}/login", follow_redirects=False)
    assert resp.status_code == 302, resp.text
    from urllib.parse import parse_qs, urlsplit

    params = parse_qs(urlsplit(resp.headers["location"]).query)
    idp["nonce"] = params["nonce"][0]
    return params["state"][0], params


# --- admin CRUD -------------------------------------------------------------


async def test_provider_crud_hides_the_secret(client, idp):
    admin = await admin_token(client)
    created = await _create_provider(client, admin)

    assert "client_secret" not in created
    assert created["client_secret_set"] is True

    listed = (await client.get("/api/admin/oidc-providers", headers=_auth(admin))).json()
    assert listed[0]["client_secret_set"] is True
    assert "client_secret" not in listed[0]


async def test_client_secret_is_encrypted_at_rest(client, idp):
    """ADR-0020: it must be retrievable, so it's encrypted — but the raw value
    must not be sitting in the column."""
    admin = await admin_token(client)
    await _create_provider(client, admin)

    # Raw SQL on purpose: selecting through the ORM (or even __table__.c) runs
    # the TypeDecorator and hands back the *decrypted* value, which would make
    # this assertion pass no matter what was stored.
    async with SessionLocal() as session:
        raw = (
            await session.execute(text("SELECT client_secret FROM oidc_providers"))
        ).scalar_one()
    assert raw is not None
    assert "super-secret-value" not in raw
    assert raw.startswith("gAAAAA"), "should be a Fernet token"

    # ...and it decrypts transparently through the ORM.
    async with SessionLocal() as session:
        provider = await session.scalar(select(OidcProvider))
    assert provider.client_secret == "super-secret-value"


async def test_provider_management_requires_the_dedicated_permission(client, idp):
    """manage_site_settings must not be enough — who can log in is its own
    grant (§7.1)."""
    admin = await admin_token(client)
    await _create_provider(client, admin)

    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "nobody", "password": "password123"},
    )
    token = reg.json()["access_token"]
    assert (
        await client.get("/api/admin/oidc-providers", headers=_auth(token))
    ).status_code == 403


async def test_secret_omitted_on_update_is_preserved(client, idp):
    admin = await admin_token(client)
    provider = await _create_provider(client, admin)

    resp = await client.patch(
        f"/api/admin/oidc-providers/{provider['id']}",
        json={"name": "Renamed"},
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["client_secret_set"] is True

    async with SessionLocal() as session:
        stored = await session.scalar(select(OidcProvider))
    assert stored.client_secret == "super-secret-value"

    # An explicit empty string clears it (public client on PKCE alone).
    cleared = await client.patch(
        f"/api/admin/oidc-providers/{provider['id']}",
        json={"client_secret": ""},
        headers=_auth(admin),
    )
    assert cleared.json()["client_secret_set"] is False


# --- public surface ---------------------------------------------------------


async def test_only_enabled_providers_are_public(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin, enabled=False, slug="off")
    await _create_provider(client, admin, enabled=True, slug="on")

    listed = (await client.get("/api/auth/oidc/providers")).json()
    assert [p["slug"] for p in listed] == ["on"]
    # The public list exposes no issuer/client_id — just enough for a button.
    assert set(listed[0]) == {"slug", "name"}


async def test_login_on_disabled_provider_404s(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin, enabled=False, slug="off")
    resp = await client.get("/api/auth/oidc/off/login", follow_redirects=False)
    assert resp.status_code == 404


async def test_login_redirect_carries_pkce_and_state(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    _, params = await _begin_login(client, idp)

    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"][0]
    assert params["response_type"] == ["code"]
    assert params["client_id"] == [CLIENT_ID]
    assert params["state"][0] and params["nonce"][0]


# --- the callback: identity resolution --------------------------------------


async def test_jit_provisions_a_participant(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    state, _ = await _begin_login(client, idp)

    resp = await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/auth/callback" in resp.headers["location"]
    assert "refresh_token" in resp.headers.get("set-cookie", "")

    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.email == "sso@example.com")
        )
        assert user is not None
        assignments = (
            await session.scalars(
                select(RoleAssignment).where(RoleAssignment.user_id == user.id)
            )
        ).all()
        roles = []
        for a in assignments:
            from models.role import Role

            roles.append((await session.get(Role, a.role_id)).name)
    # Never above Participant, whatever the IdP said.
    assert roles == ["Participant"]
    # The IdP vouched for the address, so it isn't asked to verify again.
    assert user.email_verified_at is not None


async def test_jit_user_cannot_use_local_login(client, idp):
    """Break-glass is structural: a JIT user has no password anyone knows."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    state, _ = await _begin_login(client, idp)
    await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )

    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.email == "sso@example.com")
        )
    for guess in ("", "password", "password123", user.id):
        resp = await client.post(
            "/api/auth/login",
            json={"identifier": user.display_name, "password": guess or "x"},
        )
        assert resp.status_code == 401


async def test_second_login_reuses_the_same_account(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    for _ in range(2):
        state, _ = await _begin_login(client, idp)
        resp = await client.get(
            f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert resp.status_code == 302

    async with SessionLocal() as session:
        users = (await session.scalars(
            select(User).where(User.email == "sso@example.com")
        )).all()
        identities = (await session.scalars(select(UserExternalIdentity))).all()
    assert len(users) == 1
    assert len(identities) == 1


async def test_links_to_existing_account_on_verified_email(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    reg = await client.post(
        "/api/auth/register",
        json={
            "display_name": "localuser",
            "password": "password123",
            "email": "sso@example.com",
        },
    )
    local_id = reg.json()["user"]["id"]

    state, _ = await _begin_login(client, idp)
    await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )

    async with SessionLocal() as session:
        identity = await session.scalar(select(UserExternalIdentity))
        users = (await session.scalars(
            select(User).where(User.email == "sso@example.com")
        )).all()
    assert len(users) == 1, "must link, not create a duplicate"
    assert identity.user_id == local_id
    # The pre-existing local password still works — this account is break-glass.
    assert (
        await client.post(
            "/api/auth/login",
            json={"identifier": "localuser", "password": "password123"},
        )
    ).status_code == 200


async def test_unverified_email_does_not_hijack_an_existing_account(client, idp):
    """The core linking guard: an IdP that hands back an unverified address
    must not be able to claim somebody else's local account."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    reg = await client.post(
        "/api/auth/register",
        json={
            "display_name": "victim",
            "password": "password123",
            "email": "sso@example.com",
        },
    )
    victim_id = reg.json()["user"]["id"]

    state, _ = await _begin_login(client, idp)
    idp["token_response"] = {
        "id_token": _id_token(nonce=idp["nonce"], email_verified=False),
        "access_token": "x",
    }
    resp = await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302

    async with SessionLocal() as session:
        identity = await session.scalar(select(UserExternalIdentity))
    assert identity is not None
    assert identity.user_id != victim_id, "unverified email must not link"

    async with SessionLocal() as session:
        new_user = await session.get(User, identity.user_id)
    # A separate JIT account was made, and it did not inherit the address.
    assert new_user.email is None


# --- the callback: rejection paths ------------------------------------------


async def test_unknown_state_is_rejected(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    resp = await client.get(
        "/api/auth/oidc/testidp/callback?code=abc&state=never-issued",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=invalid_state" in resp.headers["location"]


async def test_state_is_single_use(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    state, _ = await _begin_login(client, idp)

    first = await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert "error" not in first.headers["location"]

    replay = await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert "error=invalid_state" in replay.headers["location"]


async def test_tampered_signature_is_rejected(client, idp):
    """Signed by a *different* key — the signature check is what catches it."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    state, _ = await _begin_login(client, idp)

    from cryptography.hazmat.primitives import serialization

    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attacker_pem = attacker.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    idp["token_response"] = {
        "id_token": _id_token(nonce=idp["nonce"], key=attacker_pem),
        "access_token": "x",
    }
    resp = await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert "error=invalid_token" in resp.headers["location"]

    async with SessionLocal() as session:
        assert (await session.scalars(select(UserExternalIdentity))).all() == []


async def test_wrong_nonce_is_rejected(client, idp):
    """Stops an ID token obtained through another flow being replayed here."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    state, _ = await _begin_login(client, idp)
    idp["token_response"] = {
        "id_token": _id_token(nonce="a-different-nonce"),
        "access_token": "x",
    }
    resp = await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert "error=invalid_token" in resp.headers["location"]


async def test_wrong_audience_is_rejected(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    state, _ = await _begin_login(client, idp)
    idp["token_response"] = {
        "id_token": _id_token(nonce=idp["nonce"], aud="some-other-client"),
        "access_token": "x",
    }
    resp = await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert "error=invalid_token" in resp.headers["location"]


async def test_wrong_issuer_is_rejected(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    state, _ = await _begin_login(client, idp)
    idp["token_response"] = {
        "id_token": _id_token(nonce=idp["nonce"], issuer="https://evil.example.com"),
        "access_token": "x",
    }
    resp = await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert "error=invalid_token" in resp.headers["location"]


async def test_banned_user_cannot_sign_in_via_sso(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    state, _ = await _begin_login(client, idp)
    await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )

    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.email == "sso@example.com")
        )
        user.is_active = False
        await session.commit()

    state, _ = await _begin_login(client, idp)
    resp = await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert "error=account_disabled" in resp.headers["location"]


async def test_return_to_cannot_become_an_open_redirect(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    resp = await client.get(
        "/api/auth/oidc/testidp/login?return_to=https://evil.example.com",
        follow_redirects=False,
    )
    from urllib.parse import parse_qs, urlsplit

    params = parse_qs(urlsplit(resp.headers["location"]).query)
    idp["nonce"] = params["nonce"][0]
    state = params["state"][0]

    final = await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert "evil.example.com" not in final.headers["location"]


@pytest.mark.parametrize(
    "probe",
    [
        "//evil.example.com",
        # Browsers normalise backslashes to forward slashes in the path, so this
        # becomes //evil.example.com — a protocol-relative open redirect that a
        # naive "starts with / but not //" check lets straight through.
        "/\\evil.example.com",
        "https://evil.example.com",
        "/\tevil",
        "/ evil",
    ],
)
def test_return_to_allowlist_rejects_redirect_bypasses(probe):
    from routers.oidc import _safe_return_to

    assert _safe_return_to(probe) is None


def test_return_to_allows_ordinary_paths():
    from routers.oidc import _safe_return_to

    assert _safe_return_to("/challenges") == "/challenges"
    assert _safe_return_to("/a/b?c=1#d") == "/a/b?c=1#d"
