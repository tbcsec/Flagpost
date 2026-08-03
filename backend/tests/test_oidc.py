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
from sqlalchemy import func, select, text

from auth.security import create_access_token
from db import SessionLocal
from models.identity_provider import IdentityProvider, UserExternalIdentity
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


async def _create_provider(
    client,
    admin,
    *,
    enabled=True,
    slug="testidp",
    posture="open",
    email_is_authoritative=False,
) -> dict:
    resp = await client.post(
        "/api/admin/auth-providers",
        json={
            "kind": "oidc",
            "name": "Test IdP",
            "slug": slug,
            "posture": posture,
            "email_is_authoritative": email_is_authoritative,
            "secret": "super-secret-value",
            "config": {"issuer": ISSUER, "client_id": CLIENT_ID},
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

    assert "secret" not in created
    assert created["secret_set"] is True

    listed = (await client.get("/api/admin/auth-providers", headers=_auth(admin))).json()
    assert listed[0]["secret_set"] is True
    assert "secret" not in listed[0]


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
            await session.execute(text("SELECT secret FROM identity_providers"))
        ).scalar_one()
    assert raw is not None
    assert "super-secret-value" not in raw
    assert raw.startswith("gAAAAA"), "should be a Fernet token"

    # ...and it decrypts transparently through the ORM.
    async with SessionLocal() as session:
        provider = await session.scalar(select(IdentityProvider))
    assert provider.secret == "super-secret-value"


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
        await client.get("/api/admin/auth-providers", headers=_auth(token))
    ).status_code == 403


async def test_secret_omitted_on_update_is_preserved(client, idp):
    admin = await admin_token(client)
    provider = await _create_provider(client, admin)

    resp = await client.patch(
        f"/api/admin/auth-providers/{provider['id']}",
        json={"name": "Renamed"},
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["secret_set"] is True

    async with SessionLocal() as session:
        stored = await session.scalar(select(IdentityProvider))
    assert stored.secret == "super-secret-value"

    # An explicit empty string clears it (public client on PKCE alone).
    cleared = await client.patch(
        f"/api/admin/auth-providers/{provider['id']}",
        json={"secret": ""},
        headers=_auth(admin),
    )
    assert cleared.json()["secret_set"] is False


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


async def test_jit_provisions_a_user_with_no_role_assignment(client, idp):
    """A JIT user starts with *nothing*, exactly like public registration.

    Granting the competition-scoped Participant role here would mean granting it
    with ``competition_id=NULL``, which is the site-wide shape — every SSO user
    would hold challenge_view on every competition. Assert the assignment set is
    empty rather than asserting the role *name*: the name was right while the
    scope was catastrophically wrong, and a name-only check passed throughout.
    """
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
    assert assignments == []
    # The IdP vouched for the address, so it isn't asked to verify again.
    assert user.email_verified_at is not None


async def test_jit_user_cannot_see_other_competitions(client, idp):
    """The end-to-end property the missing assignment protects.

    Regression for the SSO tenancy escape: a JIT user who has joined nothing
    must not see a private competition — nor, therefore, its invite code.
    """
    admin = await admin_token(client)
    private = await client.post(
        "/api/competitions",
        json={
            "name": "Private Event",
            "description": "invite only",
            "visibility": "private",
            "participation_mode": "team",
        },
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert private.status_code == 201

    await _create_provider(client, admin)
    state, _ = await _begin_login(client, idp)
    resp = await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302

    async with SessionLocal() as session:
        user = await session.scalar(
            select(User).where(User.email == "sso@example.com")
        )
    token = create_access_token(user.id)

    listing = await client.get(
        "/api/competitions", headers={"Authorization": f"Bearer {token}"}
    )
    assert listing.status_code == 200
    assert listing.json() == []

    detail = await client.get(
        f"/api/competitions/{private.json()['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 404


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


# --- SSO admission policy (#118) ---------------------------------------------


async def _set_site_policy(*, registration_open=True, allowlist=None):
    """Set the platform admission controls the SSO gate reuses (#56 allowlist +
    the registration-open toggle)."""
    from routers.site_settings import get_or_create_settings

    async with SessionLocal() as db:
        s = await get_or_create_settings(db)
        s.registration_open = registration_open
        if allowlist is not None:
            s.email_domain_allowlist_enabled = True
            s.allowed_email_domains = allowlist
        await db.commit()


async def _sso_login(client, idp, state, *, email="sso@example.com", email_verified=True):
    """Drive the callback with a specific IdP-asserted email/verification."""
    idp["token_response"] = {
        "id_token": _id_token(nonce=idp["nonce"], email=email, email_verified=email_verified),
        "access_token": "stub-access-token",
    }
    return await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )


async def _user_by_email(email):
    async with SessionLocal() as db:
        return await db.scalar(select(User).where(func.lower(User.email) == email.lower()))


async def _external_identity_count(user_id):
    async with SessionLocal() as db:
        return len(
            (
                await db.scalars(
                    select(UserExternalIdentity).where(
                        UserExternalIdentity.user_id == user_id
                    )
                )
            ).all()
        )


async def test_sso_allowlist_admits_a_matching_domain(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    await _set_site_policy(allowlist=["example.com"])
    state, _ = await _begin_login(client, idp)

    resp = await _sso_login(client, idp, state, email="alice@example.com")
    assert resp.status_code == 302
    assert "/auth/callback" in resp.headers["location"]
    assert await _user_by_email("alice@example.com") is not None


async def test_sso_allowlist_rejects_a_non_matching_domain(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    await _set_site_policy(allowlist=["example.com"])
    state, _ = await _begin_login(client, idp)

    resp = await _sso_login(client, idp, state, email="attacker@gmail.com")
    assert resp.status_code == 302
    assert "/login?error=domain_not_allowed" in resp.headers["location"]
    # No account was provisioned.
    assert await _user_by_email("attacker@gmail.com") is None


async def test_sso_allowlist_rejects_a_matching_domain_when_unverified(client, idp):
    """The domain gate is only as trustworthy as `email_verified`; an unverified
    address at the allowed domain must not slip through."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    await _set_site_policy(allowlist=["example.com"])
    state, _ = await _begin_login(client, idp)

    resp = await _sso_login(
        client, idp, state, email="spoofer@example.com", email_verified=False
    )
    assert resp.status_code == 302
    assert "/login?error=domain_not_allowed" in resp.headers["location"]
    assert await _user_by_email("spoofer@example.com") is None


async def test_sso_registration_closed_rejects_a_new_account(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    await _set_site_policy(registration_open=False)
    state, _ = await _begin_login(client, idp)

    resp = await _sso_login(client, idp, state, email="newcomer@example.com")
    assert resp.status_code == 302
    assert "/login?error=registration_closed" in resp.headers["location"]
    assert await _user_by_email("newcomer@example.com") is None


async def test_sso_registration_closed_still_admits_an_already_linked_user(client, idp):
    """Closing registration blocks *new* accounts, never an existing SSO user —
    the already-linked path returns before the admission check."""
    admin = await admin_token(client)
    await _create_provider(client, admin)

    # First login (registration open) creates + links the identity.
    state, _ = await _begin_login(client, idp)
    first = await _sso_login(client, idp, state, email="regular@example.com")
    assert first.status_code == 302 and "/auth/callback" in first.headers["location"]

    # Now close registration and sign in again with the same identity.
    await _set_site_policy(registration_open=False)
    state2, _ = await _begin_login(client, idp)
    second = await _sso_login(client, idp, state2, email="regular@example.com")
    assert second.status_code == 302
    assert "/auth/callback" in second.headers["location"], second.headers["location"]


async def test_sso_allowlist_does_not_block_linking_to_a_pre_existing_account(client, idp):
    """The allowlist gates JIT only. Linking a verified SSO identity to an
    account that already exists is unaffected — matching #56's 'admin-created
    accounts are deliberately unaffected'."""
    admin = await admin_token(client)
    # A pre-existing local account whose domain isn't on the allowlist.
    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "prior", "email": "prior@gmail.com", "password": "password123"},
    )
    assert reg.status_code == 201, reg.text
    prior = await _user_by_email("prior@gmail.com")

    await _create_provider(client, admin)
    await _set_site_policy(allowlist=["example.com"])  # gmail.com NOT allowed
    state, _ = await _begin_login(client, idp)

    resp = await _sso_login(client, idp, state, email="prior@gmail.com", email_verified=True)
    assert resp.status_code == 302
    assert "/auth/callback" in resp.headers["location"], resp.headers["location"]
    # It linked to the existing account rather than being refused or duplicated.
    assert await _external_identity_count(prior.id) == 1


async def test_unverified_string_false_does_not_hijack_an_existing_account(client, idp):
    """`email_verified: "false"` (a string, permitted by OIDC Core) must read as
    unverified — the old bool("false")==True coercion would have linked an
    attacker's SSO identity onto a local account by email."""
    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "victim", "email": "victim@example.com", "password": "password123"},
    )
    assert reg.status_code == 201, reg.text
    victim = await _user_by_email("victim@example.com")

    admin = await admin_token(client)
    await _create_provider(client, admin)
    state, _ = await _begin_login(client, idp)

    # Same email, but the IdP marks it unverified — as the literal string "false".
    idp["token_response"] = {
        "id_token": _id_token(nonce=idp["nonce"], email="victim@example.com", email_verified="false"),
        "access_token": "stub-access-token",
    }
    resp = await client.get(
        f"/api/auth/oidc/testidp/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    # The victim's account was NOT linked to the attacker's SSO identity.
    assert await _external_identity_count(victim.id) == 0


# --- provider posture + config validation (ADR-0022) --------------------------


async def test_closed_provider_admits_when_registration_is_closed(client, idp):
    """A closed provider's enablement *is* the admission decision — the #118
    public-signup gate applies to open providers only (ADR-0022 §2/§3)."""
    admin = await admin_token(client)
    await _create_provider(client, admin, posture="closed")
    await _set_site_policy(registration_open=False)
    state, _ = await _begin_login(client, idp)

    resp = await _sso_login(client, idp, state, email="staffer@example.com")
    assert resp.status_code == 302
    assert "/auth/callback" in resp.headers["location"], resp.headers["location"]


async def test_closed_provider_ignores_the_domain_allowlist(client, idp):
    """The allowlist is a public-signup control; applying it to an
    admin-admitted directory would lock out the population the admin just
    admitted (ADR-0022 §2)."""
    admin = await admin_token(client)
    await _create_provider(client, admin, posture="closed")
    await _set_site_policy(allowlist=["example.com"])
    state, _ = await _begin_login(client, idp)

    resp = await _sso_login(client, idp, state, email="dev@other-corp.io")
    assert resp.status_code == 302
    assert "/auth/callback" in resp.headers["location"], resp.headers["location"]


async def test_closed_provider_email_cannot_claim_an_existing_account(client, idp):
    """The C1 hijack from the ADR-0022 design review: a closed provider's email
    attribute is *not* proof of address ownership, so without
    email_is_authoritative it must never link to a pre-existing local account —
    even when the provider asserts email_verified."""
    admin = await admin_token(client)
    reg = await client.post(
        "/api/auth/register",
        json={
            "display_name": "prior",
            "email": "prior@example.com",
            "password": "password123",
        },
    )
    victim_id = reg.json()["user"]["id"]

    await _create_provider(client, admin, posture="closed")
    state, _ = await _begin_login(client, idp)
    resp = await _sso_login(client, idp, state, email="prior@example.com")
    assert resp.status_code == 302
    assert "/auth/callback" in resp.headers["location"]

    # The victim gained no external identity; a separate account was JIT'd with
    # no email (the untrusted claim is dropped, not stored on the user).
    assert await _external_identity_count(victim_id) == 0
    async with SessionLocal() as db:
        jit = await db.scalar(select(User).where(User.display_name == "prior2"))
    assert jit is not None and jit.id != victim_id
    assert jit.email is None and jit.email_verified_at is None


async def test_closed_authoritative_provider_links_by_email(client, idp):
    """The admin who knows their directory verifies addresses may opt in to
    first-contact linking (email_is_authoritative, ADR-0022 §2)."""
    admin = await admin_token(client)
    reg = await client.post(
        "/api/auth/register",
        json={
            "display_name": "linkme",
            "email": "linkme@example.com",
            "password": "password123",
        },
    )
    existing_id = reg.json()["user"]["id"]

    await _create_provider(
        client, admin, posture="closed", email_is_authoritative=True
    )
    state, _ = await _begin_login(client, idp)
    # The directory doesn't assert verification; the admin's flag is the trust.
    resp = await _sso_login(
        client, idp, state, email="linkme@example.com", email_verified=False
    )
    assert resp.status_code == 302
    assert "/auth/callback" in resp.headers["location"]
    assert await _external_identity_count(existing_id) == 1


async def test_email_is_authoritative_requires_closed_posture(client, idp):
    """For an open provider email trust comes from the IdP's own claim; the
    admin override is a closed-directory concept only."""
    admin = await admin_token(client)
    resp = await client.post(
        "/api/admin/auth-providers",
        json={
            "kind": "oidc",
            "name": "Bad",
            "slug": "bad",
            "posture": "open",
            "email_is_authoritative": True,
            "config": {"issuer": ISSUER, "client_id": CLIENT_ID},
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 400


async def test_unknown_provider_kind_is_rejected(client, idp):
    admin = await admin_token(client)
    resp = await client.post(
        "/api/admin/auth-providers",
        json={"kind": "carrier-pigeon", "name": "X", "slug": "x", "config": {}},
        headers=_auth(admin),
    )
    assert resp.status_code == 400


async def test_incomplete_config_is_rejected_at_write(client, idp):
    """ADR-0022 §6: "enabled but half-configured" must not be reachable through
    the API — and a typo'd config key is a 400, not a silently ignored field."""
    admin = await admin_token(client)
    missing = await client.post(
        "/api/admin/auth-providers",
        json={
            "kind": "oidc",
            "name": "Half",
            "slug": "half",
            "config": {"issuer": ISSUER},  # no client_id
            "enabled": True,
        },
        headers=_auth(admin),
    )
    assert missing.status_code == 400

    typo = await client.post(
        "/api/admin/auth-providers",
        json={
            "kind": "oidc",
            "name": "Typo",
            "slug": "typo",
            "config": {"issuer": ISSUER, "client_id": CLIENT_ID, "isuer": "x"},
        },
        headers=_auth(admin),
    )
    assert typo.status_code == 400


async def test_corrupt_stored_config_is_a_skip_not_a_500(client, idp):
    """ADR-0022 §6: the login-time re-parse turns a drifted row (direct DB edit,
    bad migration) into an unavailable provider, not an error page."""
    admin = await admin_token(client)
    created = await _create_provider(client, admin)

    async with SessionLocal() as db:
        provider = await db.get(IdentityProvider, created["id"])
        provider.config = {"issuer": ISSUER}  # client_id lost
        await db.commit()

    resp = await client.get("/api/auth/oidc/testidp/login", follow_redirects=False)
    assert resp.status_code == 404
    # ...and the login page's button list hides it too, so the skip is
    # consistent — no button whose click lands on that 404.
    assert (await client.get("/api/auth/oidc/providers")).json() == []
