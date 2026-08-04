"""LDAP directory login (#101, ADR-0022 §5).

Like ``test_saml``, this exercises the *real* transport, not a stubbed one: the
seam substituted is ``utils.ldap._connect``/``_make_server`` — swapped for
``ldap3``'s ``MOCK_SYNC`` in-memory directory — so the search, the RFC 4515
escaping, the subject normalization and the user's own bind all run for real
through ``POST /api/auth/login``. The point of most cases is that a *bad* login
(wrong password, unknown user, empty password, ambiguous match, downed
directory) fails closed with the same generic 401 the local form gives.
"""

import pytest
from sqlalchemy import func, select

from db import SessionLocal
from models.identity_provider import IdentityProvider, UserExternalIdentity
from models.user import User
from tests.conftest import admin_token
from utils import ldap as ldap_utils
from schemas.auth_providers import LdapConfig

SVC_DN = "cn=svc,dc=corp"
SVC_PASSWORD = "svc-bind-pw"
ADA_DN = "cn=ada,ou=people,dc=corp"
ADA_UUID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
ADA_PASSWORD = "s3cret-directory-pw"

LDAP_CONFIG = {
    "server_url": "ldaps://directory.corp.example",
    "bind_dn": SVC_DN,
    "base_dn": "dc=corp",
    "search_attribute": "uid",
    "subject_attribute": "entryUUID",
    "email_attribute": "mail",
    "name_attribute": "displayName",
}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class MockDirectory:
    """A dict of DN → attributes served by ``MOCK_SYNC``; mutate ``entries`` in
    a test to shape the directory. ``connects`` counts bind attempts so tests
    can assert the directory was never consulted."""

    def __init__(self):
        self.entries = {
            SVC_DN: {"objectClass": "person", "userPassword": SVC_PASSWORD},
            ADA_DN: {
                "objectClass": "person",
                "uid": "ada",
                "entryUUID": ADA_UUID,
                "mail": "ada@corp.example",
                "displayName": "Ada L",
                "userPassword": ADA_PASSWORD,
            },
        }
        self.connects = 0


@pytest.fixture
def directory(monkeypatch) -> MockDirectory:
    from ldap3 import MOCK_SYNC, Connection, Server

    mock = MockDirectory()
    server = Server("mock-directory")

    def fake_make_server(config):
        return server

    def fake_connect(server_, user, password, *, starttls):
        mock.connects += 1
        conn = Connection(
            server_,
            user=user,
            password=password,
            client_strategy=MOCK_SYNC,
            raise_exceptions=True,
        )
        for dn, attrs in mock.entries.items():
            conn.strategy.add_entry(dn, dict(attrs))
        conn.bind()  # raises LDAPInvalidCredentialsResult on a bad bind
        return conn

    monkeypatch.setattr(ldap_utils, "_make_server", fake_make_server)
    monkeypatch.setattr(ldap_utils, "_connect", fake_connect)
    return mock


async def _create_provider(
    client,
    admin,
    *,
    enabled=True,
    email_is_authoritative=False,
    secret=SVC_PASSWORD,
    config=None,
    slug="corp",
):
    body = {
        "kind": "ldap",
        "name": "Corp Directory",
        "slug": slug,
        "posture": "closed",
        "email_is_authoritative": email_is_authoritative,
        "config": config if config is not None else dict(LDAP_CONFIG),
        "enabled": enabled,
    }
    if secret is not None:
        body["secret"] = secret
    resp = await client.post(
        "/api/admin/auth-providers", json=body, headers=_auth(admin)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client, identifier: str, password: str):
    return await client.post(
        "/api/auth/login", json={"identifier": identifier, "password": password}
    )


async def _user_by_display_name(name: str) -> User | None:
    async with SessionLocal() as db:
        return await db.scalar(
            select(User).where(func.lower(User.display_name) == name.lower())
        )


# --- happy path ---------------------------------------------------------------


async def test_ldap_login_jit_provisions_a_user(client, directory):
    admin = await admin_token(client)
    provider = await _create_provider(client, admin)

    resp = await _login(client, "ada", ADA_PASSWORD)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["access_token"]
    assert data["user"]["display_name"] == "Ada L"
    # The directory's mail attribute is NOT trusted by default (ADR-0022 §2):
    # captured on the identity link for audit, but not stamped on the account.
    assert data["user"]["email"] is None

    async with SessionLocal() as db:
        identity = await db.scalar(
            select(UserExternalIdentity).where(
                UserExternalIdentity.provider_id == provider["id"]
            )
        )
        assert identity is not None
        assert identity.subject == ADA_UUID  # the stable id, never the DN
        assert identity.email == "ada@corp.example"


async def test_second_login_reuses_the_same_account(client, directory):
    admin = await admin_token(client)
    await _create_provider(client, admin)

    first = await _login(client, "ada", ADA_PASSWORD)
    second = await _login(client, "ada", ADA_PASSWORD)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["user"]["id"] == second.json()["user"]["id"]

    async with SessionLocal() as db:
        count = await db.scalar(
            select(func.count()).select_from(UserExternalIdentity)
        )
        assert count == 1


async def test_local_password_still_wins_before_the_directory(client, directory):
    """The ADR-0017 owner (a real-password account) must never touch the
    directory — a local success short-circuits before the LDAP leg."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    directory.connects = 0

    resp = await _login(client, "admin@example.com", "changeme")
    assert resp.status_code == 200
    assert directory.connects == 0


# --- refusals (all the same generic 401) --------------------------------------


async def test_wrong_directory_password_is_a_generic_401(client, directory):
    admin = await admin_token(client)
    await _create_provider(client, admin)

    resp = await _login(client, "ada", "not-her-password")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


async def test_unknown_identifier_is_a_generic_401(client, directory):
    admin = await admin_token(client)
    await _create_provider(client, admin)

    resp = await _login(client, "nobody", "whatever")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


async def test_empty_password_never_reaches_the_directory(client, directory):
    """RFC 4513: a bind with a DN and an empty password is an *unauthenticated*
    bind that succeeds on most servers — the classic LDAP auth bypass. Refused
    before any directory I/O."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    directory.connects = 0

    resp = await _login(client, "ada", "   ")
    assert resp.status_code == 401
    assert directory.connects == 0


async def test_disabled_provider_is_not_consulted(client, directory):
    admin = await admin_token(client)
    await _create_provider(client, admin, enabled=False)
    directory.connects = 0

    resp = await _login(client, "ada", ADA_PASSWORD)
    assert resp.status_code == 401
    assert directory.connects == 0


async def test_directory_outage_is_a_generic_401_not_a_500(client, monkeypatch, directory):
    admin = await admin_token(client)
    await _create_provider(client, admin)

    def down(*args, **kwargs):
        from ldap3.core.exceptions import LDAPSocketOpenError

        raise LDAPSocketOpenError("connection refused")

    monkeypatch.setattr(ldap_utils, "_connect", down)
    resp = await _login(client, "ada", ADA_PASSWORD)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


async def test_ambiguous_match_is_refused(client, directory):
    """Two entries sharing the search attribute value: picking one would be
    guessing at an identity, so the login is refused."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    directory.entries["cn=ada2,ou=other,dc=corp"] = {
        "objectClass": "person",
        "uid": "ada",
        "entryUUID": "7cb8c921-aeae-22e2-91c5-11d15fe541d9",
        "userPassword": ADA_PASSWORD,
    }

    resp = await _login(client, "ada", ADA_PASSWORD)
    assert resp.status_code == 401


async def test_entry_without_a_stable_id_is_refused(client, directory):
    """No usable subject attribute → no login: falling back to the DN would
    re-mint the account on any OU move (ADR-0022 §5)."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    del directory.entries[ADA_DN]["entryUUID"]

    resp = await _login(client, "ada", ADA_PASSWORD)
    assert resp.status_code == 401


async def test_banned_ldap_user_cannot_log_in(client, directory):
    """The directory bind *succeeds* for a locally-banned user — the directory
    doesn't know about the ban — so the post-resolve is_active check is the
    only thing standing between them and a session (ADR-0022 §5)."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    assert (await _login(client, "ada", ADA_PASSWORD)).status_code == 200

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.display_name == "Ada L"))
        user.is_active = False
        await db.commit()

    resp = await _login(client, "ada", ADA_PASSWORD)
    assert resp.status_code == 403


# --- email trust (ADR-0022 §2) ------------------------------------------------


async def test_directory_email_does_not_claim_an_existing_account(client, directory):
    """Default posture: the mail attribute is display-only. A local account
    with the same address is NOT linked — that would let anyone who controls
    the directory entry take over the local account."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    reg = await client.post(
        "/api/auth/register",
        json={
            "display_name": "local-ada",
            "email": "ada@corp.example",
            "password": "a-local-password",
        },
    )
    assert reg.status_code == 201
    local_id = reg.json()["user"]["id"]

    resp = await _login(client, "ada", ADA_PASSWORD)
    assert resp.status_code == 200
    assert resp.json()["user"]["id"] != local_id  # a fresh JIT account


async def test_authoritative_provider_links_by_email(client, directory):
    """With email_is_authoritative set by the admin, first contact links to the
    existing local account instead of minting a new one."""
    admin = await admin_token(client)
    await _create_provider(client, admin, email_is_authoritative=True)
    reg = await client.post(
        "/api/auth/register",
        json={
            "display_name": "local-ada",
            "email": "ada@corp.example",
            "password": "a-local-password",
        },
    )
    assert reg.status_code == 201
    local_id = reg.json()["user"]["id"]

    resp = await _login(client, "ada", ADA_PASSWORD)
    assert resp.status_code == 200
    assert resp.json()["user"]["id"] == local_id


# --- admin API guardrails -----------------------------------------------------


async def test_plaintext_ldap_is_not_expressible(client):
    admin = await admin_token(client)
    config = dict(LDAP_CONFIG, server_url="ldap://directory.corp.example")
    resp = await client.post(
        "/api/admin/auth-providers",
        json={"kind": "ldap", "name": "D", "slug": "plain", "posture": "closed", "config": config},
        headers=_auth(admin),
    )
    assert resp.status_code == 400
    # …while ldap:// + StartTLS is fine.
    config["use_starttls"] = True
    resp = await client.post(
        "/api/admin/auth-providers",
        json={"kind": "ldap", "name": "D", "slug": "plain", "posture": "closed", "config": config},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text


async def test_metacharacters_in_attribute_names_are_refused(client):
    """Attribute names are interpolated into the search filter unescaped, so
    the config validator is what keeps them injection-free."""
    admin = await admin_token(client)
    config = dict(LDAP_CONFIG, search_attribute="uid)(objectClass=*")
    resp = await client.post(
        "/api/admin/auth-providers",
        json={"kind": "ldap", "name": "D", "slug": "inj", "posture": "closed", "config": config},
        headers=_auth(admin),
    )
    assert resp.status_code == 400


async def test_ldap_provider_must_be_closed_posture(client):
    admin = await admin_token(client)
    resp = await client.post(
        "/api/admin/auth-providers",
        json={
            "kind": "ldap",
            "name": "D",
            "slug": "open-ldap",
            "posture": "open",
            "config": dict(LDAP_CONFIG),
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 400


async def test_enabling_requires_the_bind_password(client):
    admin = await admin_token(client)
    # Enabled without a secret: refused — LDAP has no anonymous-bind fallback.
    resp = await client.post(
        "/api/admin/auth-providers",
        json={
            "kind": "ldap",
            "name": "D",
            "slug": "nosecret",
            "posture": "closed",
            "config": dict(LDAP_CONFIG),
            "enabled": True,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 400
    # Disabled without a secret is fine (drafting), but enabling it later
    # without one is refused too.
    created = await _create_provider(client, admin, enabled=False, secret=None, slug="draft")
    resp = await client.patch(
        f"/api/admin/auth-providers/{created['id']}",
        json={"enabled": True},
        headers=_auth(admin),
    )
    assert resp.status_code == 400
    resp = await client.patch(
        f"/api/admin/auth-providers/{created['id']}",
        json={"enabled": True, "secret": SVC_PASSWORD},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text


async def test_ldap_is_absent_from_the_public_provider_list(client, directory):
    """No dead 'Sign in with…' button: LDAP is the ordinary login form."""
    admin = await admin_token(client)
    await _create_provider(client, admin)

    resp = await client.get("/api/auth/providers")
    assert resp.status_code == 200
    assert all(p["kind"] != "ldap" for p in resp.json())


# --- utils/ldap unit coverage -------------------------------------------------


def _config(**overrides) -> LdapConfig:
    return LdapConfig(**{**LDAP_CONFIG, **overrides})


def test_search_filter_escapes_rfc4515_metacharacters():
    built = ldap_utils.search_filter("uid", r"ad)min(*\x")
    assert built == r"(uid=ad\29min\28\2a\5cx)"


def test_text_decodes_bytes_and_unwraps_lists():
    # ldap3 with no schema (get_info=None) can hand back a bytes value; str()
    # on it would store the Python repr "b'…'". _text decodes it instead.
    assert ldap_utils._text(b"ada@corp.example") == "ada@corp.example"
    assert ldap_utils._text([b"ada@corp.example"]) == "ada@corp.example"
    assert ldap_utils._text(["Ada L"]) == "Ada L"
    assert ldap_utils._text("  spaced  ") == "spaced"
    assert ldap_utils._text([]) is None
    assert ldap_utils._text(None) is None
    assert ldap_utils._text(b"") is None
    assert ldap_utils._text(b"\xff\xfe") is None  # undecodable → dropped, not a repr


def test_normalize_subject_renders_ad_objectguid_canonically():
    raw = bytes(range(1, 17))  # 01 02 03 … 10
    # AD's mixed-endian text form: first three groups byte-swapped.
    assert ldap_utils.normalize_subject(raw) == "04030201-0605-0807-090a-0b0c0d0e0f10"


def test_normalize_subject_shapes():
    assert ldap_utils.normalize_subject(["abc"]) == "abc"
    assert ldap_utils.normalize_subject("{abc}") == "abc"
    assert ldap_utils.normalize_subject(["a", "b"]) is None  # multi-valued: refuse
    assert ldap_utils.normalize_subject([]) is None
    assert ldap_utils.normalize_subject(None) is None
    assert ldap_utils.normalize_subject("  ") is None
    assert ldap_utils.normalize_subject(b"\x01\x02") == "0102"  # non-GUID bytes


def test_authenticate_refuses_blank_credentials_without_io(monkeypatch):
    def explode(*args, **kwargs):  # any connection attempt fails the test
        raise AssertionError("directory I/O attempted")

    monkeypatch.setattr(ldap_utils, "_connect", explode)
    assert ldap_utils.authenticate(_config(), SVC_PASSWORD, "ada", "   ") is None
    assert ldap_utils.authenticate(_config(), SVC_PASSWORD, "  ", "pw") is None


def test_authenticate_without_a_service_secret_is_unavailable(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("directory I/O attempted")

    monkeypatch.setattr(ldap_utils, "_connect", explode)
    with pytest.raises(ldap_utils.LdapUnavailable):
        ldap_utils.authenticate(_config(), None, "ada", "pw")


def test_ldap_config_requires_tls():
    with pytest.raises(ValueError):
        _config(server_url="ldap://x.example")  # plaintext: refused
    _config(server_url="ldap://x.example", use_starttls=True)  # StartTLS: ok
    _config(server_url="ldaps://x.example")  # LDAPS: ok
