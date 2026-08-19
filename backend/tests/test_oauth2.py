"""Plain-OAuth2 login (#193, ADR-0033).

Runs the real flow against a stubbed provider. Only the two HTTP seams are
mocked — ``exchange_code`` and ``fetch_json`` — so the parts worth testing run
for real: the claim map, the subject coercion, GitHub's separate verified-address
lookup, Discord's ``verified`` flag, and the whole state/CSRF and
identity-resolution path through the router.

The point of most of these cases is that a *bad* or unverifiable identity is
refused, which is meaningless if the code deciding that is mocked away.
"""

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from db import SessionLocal
from models.identity_provider import IdentityProvider, UserExternalIdentity
from models.user import User
from schemas.auth_providers import OAuth2Config
from tests.conftest import admin_token
from utils import oauth2 as oauth2_utils
from utils.oauth2 import (
    OAuth2Error,
    fetch_identity,
    select_primary_verified_email,
    subject_from_profile,
)

CLIENT_ID = "flagpost-oauth2-client"

GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
GITHUB_USER = "https://api.github.com/user"
GITHUB_EMAILS = "https://api.github.com/user/emails"

DISCORD_AUTHORIZE = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN = "https://discord.com/api/oauth2/token"
DISCORD_USER = "https://discord.com/api/users/@me"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _github_config(**overrides) -> dict:
    return {
        "authorize_url": GITHUB_AUTHORIZE,
        "token_url": GITHUB_TOKEN,
        "userinfo_url": GITHUB_USER,
        "emails_url": GITHUB_EMAILS,
        "client_id": CLIENT_ID,
        "scopes": "read:user user:email",
        "subject_field": "id",
        "email_field": "email",
        "name_field": "login",
        "use_pkce": False,
        **overrides,
    }


def _discord_config(**overrides) -> dict:
    return {
        "authorize_url": DISCORD_AUTHORIZE,
        "token_url": DISCORD_TOKEN,
        "userinfo_url": DISCORD_USER,
        "client_id": CLIENT_ID,
        "scopes": "identify email",
        "subject_field": "id",
        "email_field": "email",
        "name_field": "username",
        "email_verified_field": "verified",
        "use_pkce": True,
        **overrides,
    }


@pytest.fixture
def idp(monkeypatch):
    """Stub the provider's two network seams.

    ``responses`` maps a URL to the JSON that endpoint returns, so the real
    ``fetch_identity`` (claim map, email selection) runs over realistic
    payloads. ``token_error`` makes the code exchange fail.
    """
    state: dict = {"responses": {}, "token_error": None, "requested": []}

    async def _exchange_code(**kwargs):
        state["requested"].append(kwargs)
        if state["token_error"]:
            raise OAuth2Error(state["token_error"])
        return "stub-access-token"

    async def _fetch_json(url, access_token):
        if url not in state["responses"]:
            raise OAuth2Error(f"unstubbed URL {url}")
        return state["responses"][url]

    async def _noop(url):
        return None

    monkeypatch.setattr(oauth2_utils, "exchange_code", _exchange_code)
    monkeypatch.setattr(oauth2_utils, "fetch_json", _fetch_json)
    monkeypatch.setattr(oauth2_utils, "validate_endpoint_url", _noop)
    return state


async def _create_provider(
    client,
    admin,
    *,
    config: dict,
    slug="gh",
    name="GitHub",
    posture="open",
    enabled=True,
) -> dict:
    resp = await client.post(
        "/api/admin/auth-providers",
        json={
            "kind": "oauth2",
            "name": name,
            "slug": slug,
            "posture": posture,
            "secret": "super-secret-value",
            "config": config,
            "enabled": enabled,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _begin_login(client, slug="gh"):
    """Hit /login and return the state the server minted, plus the query it
    sent the browser to."""
    from urllib.parse import parse_qs, urlsplit

    resp = await client.get(f"/api/auth/oauth2/{slug}/login", follow_redirects=False)
    assert resp.status_code == 302, resp.text
    params = parse_qs(urlsplit(resp.headers["location"]).query)
    return params["state"][0], params


# --- the claim map and email trust (unit level) ------------------------------


def test_subject_is_coerced_from_a_numeric_id():
    """GitHub's `id` is a JSON number but the subject column is text."""
    assert subject_from_profile({"id": 583231}, "id") == "583231"


def test_subject_rejects_a_missing_or_boolean_field():
    """`bool` is an `int` subclass, so a naive coercion would turn every user
    with `{"id": true}` into the same subject "True"."""
    with pytest.raises(OAuth2Error):
        subject_from_profile({}, "id")
    with pytest.raises(OAuth2Error):
        subject_from_profile({"id": None}, "id")
    with pytest.raises(OAuth2Error):
        subject_from_profile({"id": True}, "id")


def test_primary_verified_email_is_selected():
    entries = [
        {"email": "alt@example.com", "primary": False, "verified": True},
        {"email": "main@example.com", "primary": True, "verified": True},
    ]
    assert select_primary_verified_email(entries) == "main@example.com"


def test_verified_but_not_primary_is_not_selected():
    """ADR-0022 §3: linking to an existing account needs the address the user
    actually presents as theirs, not merely one they control."""
    entries = [{"email": "alt@example.com", "primary": False, "verified": True}]
    assert select_primary_verified_email(entries) is None


def test_primary_but_unverified_is_not_selected():
    entries = [{"email": "main@example.com", "primary": True, "verified": False}]
    assert select_primary_verified_email(entries) is None


@pytest.mark.parametrize(
    "payload", [None, {}, "not-a-list", [None, 3, "x"], [{"primary": True}]]
)
def test_email_selection_never_raises_on_a_malformed_payload(payload):
    """The provider's response is untrusted input on an unauthenticated path."""
    assert select_primary_verified_email(payload) is None


async def test_github_identity_prefers_the_verified_address(idp):
    """GitHub's profile email is frequently null; the verified set lives on the
    second endpoint, and that address is the one we trust."""
    idp["responses"] = {
        GITHUB_USER: {"id": 42, "login": "octocat", "email": None},
        GITHUB_EMAILS: [
            {"email": "octocat@example.com", "primary": True, "verified": True}
        ],
    }
    config = OAuth2Config(**_github_config())
    subject, email, verified, claims = await fetch_identity(config, "t")
    assert (subject, email, verified) == ("42", "octocat@example.com", True)
    # `login`, not `name` — the display name is null for most GitHub accounts.
    assert claims["name"] == "octocat"


async def test_github_without_a_verified_address_is_not_trusted(idp):
    """The profile address still comes through for display, but unverified — so
    it can neither link to an existing account nor satisfy the domain gate."""
    idp["responses"] = {
        GITHUB_USER: {"id": 42, "login": "octocat", "email": "public@example.com"},
        GITHUB_EMAILS: [
            {"email": "public@example.com", "primary": True, "verified": False}
        ],
    }
    _, email, verified, _ = await fetch_identity(OAuth2Config(**_github_config()), "t")
    assert (email, verified) == ("public@example.com", False)


async def test_discord_identity_uses_its_verified_flag(idp):
    idp["responses"] = {
        DISCORD_USER: {
            "id": "80351110224678912",
            "username": "nelly",
            "email": "nelly@example.com",
            "verified": True,
        }
    }
    subject, email, verified, claims = await fetch_identity(
        OAuth2Config(**_discord_config()), "t"
    )
    assert (subject, email, verified) == (
        "80351110224678912",
        "nelly@example.com",
        True,
    )
    assert claims["name"] == "nelly"


async def test_discord_unverified_flag_is_honoured(idp):
    idp["responses"] = {
        DISCORD_USER: {
            "id": "1",
            "username": "nelly",
            "email": "nelly@example.com",
            "verified": False,
        }
    }
    _, _, verified, _ = await fetch_identity(OAuth2Config(**_discord_config()), "t")
    assert verified is False


async def test_no_verification_evidence_means_unverified(idp):
    """A provider with neither a verified flag nor an emails endpoint gives us
    no evidence, so the answer is False — never an optimistic default."""
    idp["responses"] = {DISCORD_USER: {"id": "1", "email": "who@example.com"}}
    config = OAuth2Config(
        **_discord_config(email_verified_field=None, use_pkce=False)
    )
    _, email, verified, _ = await fetch_identity(config, "t")
    assert (email, verified) == ("who@example.com", False)


# --- the token exchange's failure shapes -------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        return self._response

    async def get(self, *args, **kwargs):
        return self._response


def _stub_http(monkeypatch, response):
    monkeypatch.setattr(oauth2_utils, "validate_endpoint_url", _passthrough)
    monkeypatch.setattr(
        oauth2_utils.httpx, "AsyncClient", lambda **kw: _FakeClient(response)
    )


async def _passthrough(url):
    return None


async def test_token_error_reported_with_http_200_is_caught(monkeypatch):
    """GitHub answers a bad or replayed code with **200** and an `error` key.
    A status-only check would sail past it and fail confusingly later."""
    _stub_http(monkeypatch, _FakeResponse(200, {"error": "bad_verification_code"}))
    with pytest.raises(OAuth2Error, match="bad_verification_code"):
        await oauth2_utils.exchange_code(
            token_url=GITHUB_TOKEN,
            code="c",
            redirect_uri="https://x/cb",
            client_id=CLIENT_ID,
            client_secret="s",
        )


async def test_token_response_without_an_access_token_is_rejected(monkeypatch):
    _stub_http(monkeypatch, _FakeResponse(200, {"token_type": "bearer"}))
    with pytest.raises(OAuth2Error, match="no access_token"):
        await oauth2_utils.exchange_code(
            token_url=GITHUB_TOKEN,
            code="c",
            redirect_uri="https://x/cb",
            client_id=CLIENT_ID,
            client_secret="s",
        )


# --- write-time config validation --------------------------------------------


def test_config_rejects_a_non_absolute_endpoint():
    with pytest.raises(ValidationError):
        OAuth2Config(**_github_config(userinfo_url="/user"))


def test_config_rejects_a_hostile_claim_field_name():
    """Claim names are dict keys; the pattern keeps a drifted manifest from
    naming something unexpected."""
    with pytest.raises(ValidationError):
        OAuth2Config(**_github_config(subject_field="../../etc/passwd"))


def test_config_defaults_are_conservative():
    config = OAuth2Config(
        authorize_url=GITHUB_AUTHORIZE,
        token_url=GITHUB_TOKEN,
        userinfo_url=GITHUB_USER,
        client_id=CLIENT_ID,
    )
    assert config.use_pkce is False
    assert config.email_verified_field is None
    assert config.emails_url is None


async def test_admin_can_create_an_oauth2_provider(client, idp):
    admin = await admin_token(client)
    created = await _create_provider(client, admin, config=_github_config())
    assert created["kind"] == "oauth2"
    # The callback URL an admin must register upstream — the most common reason
    # an OAuth setup fails, so it's computed server-side like OIDC's.
    assert created["redirect_uri"].endswith("/api/auth/oauth2/gh/callback")
    assert created["secret_set"] is True
    assert "secret" not in created


async def test_create_rejects_an_unreachable_endpoint(client):
    """The egress check runs at write time so the admin finds out immediately —
    here it is *not* stubbed, so a private address is genuinely refused."""
    admin = await admin_token(client)
    resp = await client.post(
        "/api/admin/auth-providers",
        json={
            "kind": "oauth2",
            "name": "Bad",
            "slug": "bad",
            "posture": "open",
            "config": _github_config(userinfo_url="http://169.254.169.254/latest"),
            "enabled": False,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 400, resp.text


async def test_oauth2_provider_may_be_open(client, idp):
    """GitHub/Discord are public IdPs, so `open` must be expressible — the
    posture invariant fixes only SAML/LDAP to closed (ADR-0022 §2)."""
    admin = await admin_token(client)
    created = await _create_provider(client, admin, config=_github_config())
    assert created["posture"] == "open"


# --- the login leg ------------------------------------------------------------


async def test_login_redirect_carries_state_and_no_pkce_by_default(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin, config=_github_config())
    state, params = await _begin_login(client)
    assert state
    assert params["client_id"] == [CLIENT_ID]
    assert params["response_type"] == ["code"]
    assert params["scope"] == ["read:user user:email"]
    # GitHub's OAuth Apps ignore PKCE, so the preset leaves it off.
    assert "code_challenge" not in params


async def test_login_redirect_carries_pkce_when_enabled(client, idp):
    admin = await admin_token(client)
    await _create_provider(
        client, admin, config=_discord_config(), slug="dc", name="Discord"
    )
    _, params = await _begin_login(client, slug="dc")
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"]


async def test_login_on_a_disabled_provider_404s(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin, config=_github_config(), enabled=False)
    resp = await client.get("/api/auth/oauth2/gh/login", follow_redirects=False)
    assert resp.status_code == 404


# --- end to end ---------------------------------------------------------------


async def test_github_sign_in_provisions_a_user(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin, config=_github_config())
    idp["responses"] = {
        GITHUB_USER: {"id": 583231, "login": "octocat", "email": None},
        GITHUB_EMAILS: [
            {"email": "octocat@example.com", "primary": True, "verified": True}
        ],
    }

    state, _ = await _begin_login(client)
    resp = await client.get(
        f"/api/auth/oauth2/gh/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    assert "error=" not in resp.headers["location"]

    async with SessionLocal() as db:
        link = await db.scalar(
            select(UserExternalIdentity).where(
                UserExternalIdentity.subject == "583231"
            )
        )
        assert link is not None
        user = await db.get(User, link.user_id)
        assert user.display_name == "octocat"
        # A verified address is trusted, so it lands on the account.
        assert user.email == "octocat@example.com"
        assert user.email_verified_at is not None


async def test_discord_sign_in_provisions_a_user(client, idp):
    admin = await admin_token(client)
    await _create_provider(
        client, admin, config=_discord_config(), slug="dc", name="Discord"
    )
    idp["responses"] = {
        DISCORD_USER: {
            "id": "80351110224678912",
            "username": "nelly",
            "email": "nelly@example.com",
            "verified": True,
        }
    }

    state, _ = await _begin_login(client, slug="dc")
    resp = await client.get(
        f"/api/auth/oauth2/dc/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    assert "error=" not in resp.headers["location"]

    async with SessionLocal() as db:
        link = await db.scalar(
            select(UserExternalIdentity).where(
                UserExternalIdentity.subject == "80351110224678912"
            )
        )
        assert link is not None


async def test_second_login_reuses_the_same_account(client, idp):
    """Sub-first: the same provider subject must land on the same user, even
    though the address changed upstream."""
    admin = await admin_token(client)
    await _create_provider(client, admin, config=_github_config())

    for address in ("first@example.com", "second@example.com"):
        idp["responses"] = {
            GITHUB_USER: {"id": 7, "login": "octocat", "email": None},
            GITHUB_EMAILS: [{"email": address, "primary": True, "verified": True}],
        }
        state, _ = await _begin_login(client)
        resp = await client.get(
            f"/api/auth/oauth2/gh/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert resp.status_code == 302

    async with SessionLocal() as db:
        users = (
            await db.scalars(
                select(User).where(User.display_name.like("octocat%"))
            )
        ).all()
        assert len(users) == 1


async def test_unverified_email_does_not_hijack_an_existing_account(client, idp):
    """The security property: an open provider's unverified address must not
    attach a new external identity to somebody's existing local account."""
    admin = await admin_token(client)
    await _create_provider(client, admin, config=_github_config())

    victim = await client.post(
        "/api/auth/register",
        json={
            "display_name": "victim",
            "email": "victim@example.com",
            "password": "password123",
        },
    )
    assert victim.status_code in (200, 201), victim.text

    idp["responses"] = {
        GITHUB_USER: {"id": 9, "login": "attacker", "email": "victim@example.com"},
        # Claimed, but GitHub says it isn't verified.
        GITHUB_EMAILS: [
            {"email": "victim@example.com", "primary": True, "verified": False}
        ],
    }
    state, _ = await _begin_login(client)
    resp = await client.get(
        f"/api/auth/oauth2/gh/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert resp.status_code == 302

    async with SessionLocal() as db:
        link = await db.scalar(
            select(UserExternalIdentity).where(UserExternalIdentity.subject == "9")
        )
        victim_user = await db.scalar(
            select(User).where(User.display_name == "victim")
        )
        # A separate account was provisioned; the victim was untouched.
        assert link is not None
        assert link.user_id != victim_user.id


# --- state handling -----------------------------------------------------------


async def test_unknown_state_is_rejected(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin, config=_github_config())
    resp = await client.get(
        "/api/auth/oauth2/gh/callback?code=abc&state=never-issued",
        follow_redirects=False,
    )
    assert "error=invalid_state" in resp.headers["location"]


async def test_state_is_single_use(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin, config=_github_config())
    idp["responses"] = {
        GITHUB_USER: {"id": 11, "login": "octocat", "email": None},
        GITHUB_EMAILS: [{"email": "o@example.com", "primary": True, "verified": True}],
    }
    state, _ = await _begin_login(client)
    first = await client.get(
        f"/api/auth/oauth2/gh/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert "error=" not in first.headers["location"]
    replay = await client.get(
        f"/api/auth/oauth2/gh/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert "error=invalid_state" in replay.headers["location"]


async def test_provider_error_is_a_generic_redirect(client, idp):
    admin = await admin_token(client)
    await _create_provider(client, admin, config=_github_config())
    resp = await client.get(
        "/api/auth/oauth2/gh/callback?error=access_denied",
        follow_redirects=False,
    )
    assert "error=provider_denied" in resp.headers["location"]


async def test_token_exchange_failure_is_a_generic_redirect(client, idp):
    """The provider's own message never reaches the browser — it can carry
    endpoint and client detail an unauthenticated visitor shouldn't see."""
    admin = await admin_token(client)
    await _create_provider(client, admin, config=_github_config())
    idp["token_error"] = "token endpoint returned error 'bad_verification_code'"
    state, _ = await _begin_login(client)
    resp = await client.get(
        f"/api/auth/oauth2/gh/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    assert "error=invalid_token" in resp.headers["location"]
    assert "bad_verification_code" not in resp.headers["location"]


# --- the public list ----------------------------------------------------------


async def test_public_list_includes_oauth2_with_its_brand(client, idp):
    """`oauth2` is a redirect kind, so it gets a login button — branded from the
    authorize URL's host at read time (ADR-0024)."""
    admin = await admin_token(client)
    await _create_provider(client, admin, config=_github_config())
    await _create_provider(
        client, admin, config=_discord_config(), slug="dc", name="Discord"
    )

    listed = (await client.get("/api/auth/providers")).json()
    by_slug = {p["slug"]: p for p in listed}
    assert by_slug["gh"]["kind"] == "oauth2"
    assert by_slug["gh"]["brand"] == "github"
    assert by_slug["dc"]["brand"] == "discord"
    # No config leaks to an unauthenticated page.
    assert "config" not in by_slug["gh"]


async def test_corrupt_stored_config_is_a_skip_not_a_500(client, idp):
    """ADR-0022 §6: a row that no longer validates is indistinguishable from a
    disabled provider, rather than a 500 in a user's face."""
    admin = await admin_token(client)
    created = await _create_provider(client, admin, config=_github_config())

    async with SessionLocal() as db:
        provider = await db.get(IdentityProvider, created["id"])
        provider.config = {"authorize_url": GITHUB_AUTHORIZE}  # rest lost
        await db.commit()

    resp = await client.get("/api/auth/oauth2/gh/login", follow_redirects=False)
    assert resp.status_code == 404
    assert (await client.get("/api/auth/providers")).json() == []
