"""SAML 2.0 SP login (#100, ADR-0022 §4).

Like ``test_oidc``, this runs the *real* flow against a stubbed IdP: a genuine
RSA keypair signs the assertion, and validation runs for real inside
``python3-saml`` — the point of most cases is that a *bad* assertion (unsigned,
tampered, expired, replayed, wrapped) is rejected, which is meaningless if
nothing verifies signatures.

The SP is pinned to ``https://sp.example.com`` via ``PUBLIC_BASE_URL`` so the ACS
URL is https (python3-saml refuses a plain-http SP) and the reconstructed
``Destination`` matches what the assertion claims.
"""

import base64
import datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from onelogin.saml2.constants import OneLogin_Saml2_Constants as C
from onelogin.saml2.utils import OneLogin_Saml2_Utils
from sqlalchemy import func, select

from config import settings as app_settings
from db import SessionLocal
from models.identity_provider import AuthLoginState, IdentityProvider, UserExternalIdentity
from models.user import User
from tests.conftest import admin_token

SP_ORIGIN = "https://sp.example.com"
SP_ENTITY = "https://sp.example.com/saml/sp"
IDP_ENTITY = "https://idp.example.com/metadata"
IDP_SSO = "https://idp.example.com/sso"
SLUG = "campus"
ACS = f"{SP_ORIGIN}/api/auth/saml/{SLUG}/acs"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_now0 = datetime.datetime.now(datetime.timezone.utc)
_CERT = (
    x509.CertificateBuilder()
    .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-idp")]))
    .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-idp")]))
    .public_key(_KEY.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(_now0 - datetime.timedelta(days=1))
    .not_valid_after(_now0 + datetime.timedelta(days=3650))
    .sign(_KEY, hashes.SHA256())
)
_KEY_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
).decode()
_CERT_PEM = _CERT.public_bytes(serialization.Encoding.PEM).decode()
# A different keypair whose cert the SP does NOT trust (for the wrong-signer case).
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY_PEM = _OTHER_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
).decode()
_OTHER_CERT_PEM = (
    x509.CertificateBuilder()
    .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "evil")]))
    .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "evil")]))
    .public_key(_OTHER_KEY.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(_now0 - datetime.timedelta(days=1))
    .not_valid_after(_now0 + datetime.timedelta(days=3650))
    .sign(_OTHER_KEY, hashes.SHA256())
    .public_bytes(serialization.Encoding.PEM)
    .decode()
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _public_base(monkeypatch):
    """Pin the SP origin so the ACS URL is https and Destination checks resolve."""
    monkeypatch.setattr(app_settings, "public_base_url", SP_ORIGIN)


def _iso(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _assertion_xml(
    *,
    request_id: str,
    subject: str,
    email: str | None,
    name: str | None,
    audience: str,
    nameid_format: str,
    not_before_delta: int,
    not_after_delta: int,
    omit_in_response_to: bool = False,
) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    nb = _iso(now + datetime.timedelta(seconds=not_before_delta))
    na = _iso(now + datetime.timedelta(seconds=not_after_delta))
    attrs = ""
    if email is not None:
        attrs += f'<saml:Attribute Name="email"><saml:AttributeValue>{email}</saml:AttributeValue></saml:Attribute>'
    if name is not None:
        attrs += f'<saml:Attribute Name="displayName"><saml:AttributeValue>{name}</saml:AttributeValue></saml:Attribute>'
    irt = "" if omit_in_response_to else f'InResponseTo="{request_id}" '
    return f"""<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_assert_{request_id}" Version="2.0" IssueInstant="{_iso(now)}">
<saml:Issuer>{IDP_ENTITY}</saml:Issuer>
<saml:Subject><saml:NameID Format="{nameid_format}">{subject}</saml:NameID>
<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer"><saml:SubjectConfirmationData {irt}Recipient="{ACS}" NotOnOrAfter="{na}"/></saml:SubjectConfirmation></saml:Subject>
<saml:Conditions NotBefore="{nb}" NotOnOrAfter="{na}"><saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction></saml:Conditions>
<saml:AuthnStatement AuthnInstant="{_iso(now)}" SessionIndex="_sess_{request_id}"><saml:AuthnContext><saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport</saml:AuthnContextClassRef></saml:AuthnContext></saml:AuthnStatement>
<saml:AttributeStatement>{attrs}</saml:AttributeStatement>
</saml:Assertion>"""


def make_saml_response(
    request_id: str,
    *,
    subject: str = "saml-user-1",
    email: str | None = "ada@example.com",
    name: str | None = "Ada Lovelace",
    audience: str = SP_ENTITY,
    nameid_format: str = C.NAMEID_PERSISTENT,
    not_before_delta: int = -60,
    not_after_delta: int = 300,
    omit_in_response_to: bool = False,
    sign: bool = True,
    sign_message_not_assertion: bool = False,
    signer_key: str | None = None,
    signer_cert: str | None = None,
    tamper_email: str | None = None,
    extra_unsigned_assertion: bool = False,
) -> str:
    """A base64 SAML Response for the HTTP-POST binding. Signs the assertion by
    default with the IdP's trusted key. ``sign_message_not_assertion`` signs the
    *response envelope* instead, leaving the assertion unsigned — the case that
    proves we require the assertion itself to be signed."""
    assertion = _assertion_xml(
        request_id=request_id,
        subject=subject,
        email=email,
        name=name,
        audience=audience,
        nameid_format=nameid_format,
        not_before_delta=not_before_delta,
        not_after_delta=not_after_delta,
        omit_in_response_to=omit_in_response_to,
    )
    if sign and not sign_message_not_assertion:
        signed = OneLogin_Saml2_Utils.add_sign(
            assertion,
            signer_key or _KEY_PEM,
            signer_cert or _CERT_PEM,
            sign_algorithm=C.RSA_SHA256,
            digest_algorithm=C.SHA256,
        )
        assertion = signed.decode() if isinstance(signed, bytes) else signed
    if tamper_email is not None:
        # Rewrite the email *after* signing → the signature no longer matches.
        assertion = assertion.replace("ada@example.com", tamper_email)
    forged = ""
    if extra_unsigned_assertion:
        # A classic XSW shape: a second, unsigned assertion smuggled alongside
        # the legitimate one. The library must not treat it as authenticated.
        forged = _assertion_xml(
            request_id=request_id,
            subject="attacker",
            email="attacker@evil.example",
            name="Mallory",
            audience=SP_ENTITY,
            nameid_format=C.NAMEID_PERSISTENT,
            not_before_delta=-60,
            not_after_delta=300,
        )
    now = _iso(datetime.datetime.now(datetime.timezone.utc))
    resp_irt = "" if omit_in_response_to else f' InResponseTo="{request_id}"'
    response = f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_resp_{request_id}" Version="2.0" IssueInstant="{now}" Destination="{ACS}"{resp_irt}><saml:Issuer>{IDP_ENTITY}</saml:Issuer><samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>{assertion}{forged}</samlp:Response>"""
    if sign and sign_message_not_assertion:
        signed = OneLogin_Saml2_Utils.add_sign(
            response,
            signer_key or _KEY_PEM,
            signer_cert or _CERT_PEM,
            sign_algorithm=C.RSA_SHA256,
            digest_algorithm=C.SHA256,
        )
        response = signed.decode() if isinstance(signed, bytes) else signed
    return base64.b64encode(
        response.encode() if isinstance(response, str) else response
    ).decode()


async def _create_provider(client, admin, *, enabled=True, email_is_authoritative=False):
    resp = await client.post(
        "/api/admin/auth-providers",
        json={
            "kind": "saml",
            "name": "Campus IdP",
            "slug": SLUG,
            "posture": "closed",
            "email_is_authoritative": email_is_authoritative,
            "config": {
                "idp_entity_id": IDP_ENTITY,
                "idp_sso_url": IDP_SSO,
                "idp_x509_cert": _CERT_PEM,
                "sp_entity_id": SP_ENTITY,
            },
            "enabled": enabled,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _begin_login(client) -> tuple[str, str]:
    """Hit /login, return (relay_state, request_id). RelayState is our state
    token; request_id is the AuthnRequest id the router stored to enforce
    InResponseTo."""
    resp = await client.get(f"/api/auth/saml/{SLUG}/login", follow_redirects=False)
    assert resp.status_code == 302, resp.text
    from urllib.parse import parse_qs, urlsplit

    params = parse_qs(urlsplit(resp.headers["location"]).query)
    relay_state = params["RelayState"][0]
    async with SessionLocal() as db:
        row = await db.get(AuthLoginState, relay_state)
        assert row is not None
        return relay_state, row.nonce


async def _acs(client, relay_state: str, saml_response: str):
    return await client.post(
        f"/api/auth/saml/{SLUG}/acs",
        data={"SAMLResponse": saml_response, "RelayState": relay_state},
        follow_redirects=False,
    )


async def _user_by_email(email):
    async with SessionLocal() as db:
        return await db.scalar(
            select(User).where(func.lower(User.email) == email.lower())
        )


# --- happy path + gating ------------------------------------------------------


async def test_login_redirects_to_the_idp_with_relaystate(client):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    resp = await client.get(f"/api/auth/saml/{SLUG}/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].startswith(IDP_SSO)
    assert "SAMLRequest=" in resp.headers["location"]


async def test_login_on_disabled_provider_404s(client):
    admin = await admin_token(client)
    await _create_provider(client, admin, enabled=False)
    resp = await client.get(f"/api/auth/saml/{SLUG}/login", follow_redirects=False)
    assert resp.status_code == 404


async def test_saml_appears_in_the_unified_provider_list(client):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    listed = (await client.get("/api/auth/providers")).json()
    # brand is None for every SAML provider — it's an OIDC-issuer marker
    # (utils/provider_presets.brand_for_provider, ADR-0024).
    assert {"slug": SLUG, "name": "Campus IdP", "kind": "saml", "brand": None} in listed


async def test_valid_assertion_jit_provisions_a_user(client):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay, rid = await _begin_login(client)
    resp = await _acs(client, relay, make_saml_response(rid))
    assert resp.status_code == 302
    assert "/auth/callback" in resp.headers["location"]
    assert "set-cookie" in {k.lower() for k in resp.headers}
    # A closed provider that isn't email-authoritative stamps no email on the
    # JIT user (the address isn't trusted) — but the account exists, keyed on
    # the NameID subject.
    async with SessionLocal() as db:
        identity = await db.scalar(
            select(UserExternalIdentity).where(
                UserExternalIdentity.subject == "saml-user-1"
            )
        )
        assert identity is not None
        user = await db.get(User, identity.user_id)
        assert user.email is None and user.email_verified_at is None


async def test_second_login_reuses_the_same_account(client):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay1, rid1 = await _begin_login(client)
    assert (await _acs(client, relay1, make_saml_response(rid1))).status_code == 302
    relay2, rid2 = await _begin_login(client)
    assert (await _acs(client, relay2, make_saml_response(rid2))).status_code == 302
    async with SessionLocal() as db:
        count = await db.scalar(
            select(func.count(UserExternalIdentity.id)).where(
                UserExternalIdentity.subject == "saml-user-1"
            )
        )
        assert count == 1


async def test_authoritative_provider_links_by_email(client):
    admin = await admin_token(client)
    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "prior", "email": "ada@example.com", "password": "password123"},
    )
    existing_id = reg.json()["user"]["id"]
    await _create_provider(client, admin, email_is_authoritative=True)
    relay, rid = await _begin_login(client)
    resp = await _acs(client, relay, make_saml_response(rid, email="ada@example.com"))
    assert resp.status_code == 302 and "/auth/callback" in resp.headers["location"]
    async with SessionLocal() as db:
        identity = await db.scalar(
            select(UserExternalIdentity).where(
                UserExternalIdentity.subject == "saml-user-1"
            )
        )
        assert identity is not None and identity.user_id == existing_id


# --- the security battery (the point of the feature) -------------------------


async def test_unsigned_assertion_is_rejected(client):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay, rid = await _begin_login(client)
    resp = await _acs(client, relay, make_saml_response(rid, sign=False))
    assert "error=invalid_token" in resp.headers["location"]
    assert await _user_by_email("ada@example.com") is None


async def test_tampered_assertion_is_rejected(client):
    """Rewriting a value after signing must break signature validation."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay, rid = await _begin_login(client)
    resp = await _acs(
        client, relay, make_saml_response(rid, tamper_email="attacker@evil.example")
    )
    assert "error=invalid_token" in resp.headers["location"]


async def test_message_signed_but_unsigned_assertion_is_rejected(client):
    """A validly IdP-signed *response envelope* wrapping an *unsigned* assertion
    must be refused — we require the assertion itself to be signed
    (``wantAssertionsSigned``), not merely the message, which is the XSW-adjacent
    protection that stops a signed-envelope-with-swapped-assertion attack."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay, rid = await _begin_login(client)
    resp = await _acs(
        client, relay, make_saml_response(rid, sign_message_not_assertion=True)
    )
    assert "error=invalid_token" in resp.headers["location"]


async def test_assertion_signed_by_an_untrusted_key_is_rejected(client):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay, rid = await _begin_login(client)
    resp = await _acs(
        client,
        relay,
        make_saml_response(rid, signer_key=_OTHER_KEY_PEM, signer_cert=_OTHER_CERT_PEM),
    )
    assert "error=invalid_token" in resp.headers["location"]


async def test_expired_conditions_are_rejected(client):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay, rid = await _begin_login(client)
    resp = await _acs(
        client, relay, make_saml_response(rid, not_before_delta=-600, not_after_delta=-300)
    )
    assert "error=invalid_token" in resp.headers["location"]


async def test_wrong_audience_is_rejected(client):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay, rid = await _begin_login(client)
    resp = await _acs(
        client, relay, make_saml_response(rid, audience="https://someone-else.example")
    )
    assert "error=invalid_token" in resp.headers["location"]


async def test_mismatched_inresponseto_is_rejected(client):
    """An assertion answering a request we didn't issue (replay / injection)."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay, _rid = await _begin_login(client)
    resp = await _acs(client, relay, make_saml_response("_not_our_request_id"))
    assert "error=invalid_token" in resp.headers["location"]


async def test_unsolicited_assertion_without_inresponseto_is_rejected(client):
    """An IdP-initiated / unsolicited assertion — validly signed, correct
    audience and destination, but carrying no InResponseTo at all — must be
    refused (SP-initiated only, ADR-0022 §4). python3-saml only checks
    InResponseTo when it's *present*, so the ACS enforces the binding itself;
    without that, an attacker who mints a RelayState via /login could replay a
    signed IdP-initiated assertion into a session."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay, rid = await _begin_login(client)
    resp = await _acs(
        client, relay, make_saml_response(rid, omit_in_response_to=True)
    )
    assert "error=invalid_token" in resp.headers["location"]
    assert await _user_by_email("ada@example.com") is None


async def test_relaystate_is_single_use(client):
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay, rid = await _begin_login(client)
    first = await _acs(client, relay, make_saml_response(rid))
    assert first.status_code == 302 and "/auth/callback" in first.headers["location"]
    # Replaying the same RelayState finds no state row — the CSRF/replay guard.
    second = await _acs(client, relay, make_saml_response(rid))
    assert "error=invalid_state" in second.headers["location"]


async def test_transient_nameid_is_rejected(client):
    """A transient NameID changes each login; accepting it would JIT a fresh
    account every time (ADR-0022 §4)."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay, rid = await _begin_login(client)
    resp = await _acs(
        client, relay, make_saml_response(rid, nameid_format=C.NAMEID_TRANSIENT)
    )
    assert "error=invalid_token" in resp.headers["location"]


async def test_signature_wrapping_extra_assertion_is_rejected(client):
    """A second, unsigned assertion smuggled into the response (XSW) must not be
    accepted — python3-saml refuses a response carrying more than one assertion."""
    admin = await admin_token(client)
    await _create_provider(client, admin)
    relay, rid = await _begin_login(client)
    resp = await _acs(
        client, relay, make_saml_response(rid, extra_unsigned_assertion=True)
    )
    assert "error=invalid_token" in resp.headers["location"]
    assert await _user_by_email("attacker@evil.example") is None


async def test_banned_user_cannot_sign_in_via_saml(client):
    admin = await admin_token(client)
    await _create_provider(client, admin, email_is_authoritative=True)
    # First login creates + links the account.
    relay, rid = await _begin_login(client)
    assert (await _acs(client, relay, make_saml_response(rid))).status_code == 302
    async with SessionLocal() as db:
        identity = await db.scalar(
            select(UserExternalIdentity).where(
                UserExternalIdentity.subject == "saml-user-1"
            )
        )
        user = await db.get(User, identity.user_id)
        user.is_active = False
        await db.commit()
    # A banned user's next login is refused after resolution (the directory
    # can't know about a local ban — the post-resolve is_active check is it).
    relay2, rid2 = await _begin_login(client)
    resp = await _acs(client, relay2, make_saml_response(rid2))
    assert "error=account_disabled" in resp.headers["location"]


# --- SP metadata --------------------------------------------------------------


async def test_metadata_endpoint_serves_sp_descriptor(client):
    admin = await admin_token(client)
    await _create_provider(client, admin, enabled=False)  # available before enable
    resp = await client.get(f"/api/auth/saml/{SLUG}/metadata")
    assert resp.status_code == 200
    assert "samlmetadata" in resp.headers["content-type"]
    body = resp.text
    assert ACS in body
    assert SP_ENTITY in body


# --- admin invariant ----------------------------------------------------------


async def test_saml_provider_must_be_closed_posture(client):
    admin = await admin_token(client)
    resp = await client.post(
        "/api/admin/auth-providers",
        json={
            "kind": "saml",
            "name": "Bad",
            "slug": "bad-saml",
            "posture": "open",
            "config": {
                "idp_entity_id": IDP_ENTITY,
                "idp_sso_url": IDP_SSO,
                "idp_x509_cert": _CERT_PEM,
                "sp_entity_id": SP_ENTITY,
            },
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 400
