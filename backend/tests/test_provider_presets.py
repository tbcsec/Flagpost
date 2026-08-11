"""Built-in SSO provider presets (ADR-0024).

The catalog is data, so most of this is contract pinning: the two presets the
admin UI renders setup cards from, that each preset actually round-trips the
write path it prefills (a preset whose config the create API would refuse is
worse than no preset), and that the public ``brand`` marker is derived from
the stored issuer — never stored — so it follows whatever an admin actually
configured, preset or not.
"""

import re

import pytest
from pydantic import ValidationError

from schemas.auth_providers import (
    PROVIDER_CONFIG_MODELS,
    OidcConfig,
    ProviderPresetOut,
)
from tests.conftest import admin_token
from utils.provider_presets import PROVIDER_PRESETS, brand_for_provider

PRESETS_URL = "/api/admin/auth-providers/presets"

# A syntactically valid Entra tenant GUID (any GUID works — the preset's
# pattern is a shape check, not a directory lookup).
SAMPLE_TENANT = "12345678-abcd-ef01-2345-6789abcdef01"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _preset(preset_id: str) -> dict:
    return next(p for p in PROVIDER_PRESETS if p["id"] == preset_id)


@pytest.fixture
def no_issuer_probe(monkeypatch):
    """Skip the write-time issuer reachability probe — the same network seam
    test_oidc's idp fixture stubs; everything else runs for real."""
    from utils import oidc as oidc_utils

    async def _noop(url):
        return None

    monkeypatch.setattr(oidc_utils, "validate_issuer_url", _noop)


# --- the admin endpoint -------------------------------------------------------


async def test_presets_require_authentication(client):
    assert (await client.get(PRESETS_URL)).status_code == 401


async def test_presets_require_the_management_permission(client):
    """Same bar as the rest of the surface: presets prefill who can log in,
    so a plain participant has no business reading the setup guidance."""
    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "nobody", "password": "password123"},
    )
    token = reg.json()["access_token"]
    assert (await client.get(PRESETS_URL, headers=_auth(token))).status_code == 403


async def test_presets_list_google_and_microsoft(client):
    admin = await admin_token(client)
    resp = await client.get(PRESETS_URL, headers=_auth(admin))
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert [p["id"] for p in body] == ["google", "microsoft"]
    # Every entry round-trips the response model — the frontend builds forms
    # from exactly this shape.
    for entry in body:
        ProviderPresetOut.model_validate(entry)

    google = next(p for p in body if p["id"] == "google")
    assert google["kind"] == "oidc"
    assert google["issuer"] == "https://accounts.google.com"
    assert google["issuer_template"] is None
    assert google["params"] == []
    assert google["scopes"] == "openid email profile"
    assert google["default_slug"] == "google"
    assert google["posture"] == "open"
    assert google["setup_url"] == "https://console.cloud.google.com/apis/credentials"
    assert google["notes"]

    microsoft = next(p for p in body if p["id"] == "microsoft")
    assert microsoft["kind"] == "oidc"
    assert microsoft["issuer"] is None
    assert (
        microsoft["issuer_template"]
        == "https://login.microsoftonline.com/{tenant_id}/v2.0"
    )
    assert [param["key"] for param in microsoft["params"]] == ["tenant_id"]
    param = microsoft["params"][0]
    assert set(param) == {
        "key", "label", "placeholder", "pattern", "normalize", "help",
    }
    # Entra canonicalizes the GUID to lowercase and the issuer checks are
    # case-sensitive — the client must normalize an uppercase paste.
    assert param["normalize"] == "lowercase"
    # A single-tenant directory is ADR-0022 §2's closed category; an open
    # default would apply the public-registration gate to the org's members.
    assert microsoft["posture"] == "closed"
    assert microsoft["setup_url"] == "https://entra.microsoft.com"


# --- presets must round-trip the write path they prefill -----------------------


def test_every_preset_kind_is_creatable():
    """A preset for a kind the create API would refuse is a dead card."""
    for preset in PROVIDER_PRESETS:
        assert preset["kind"] in PROVIDER_CONFIG_MODELS, preset["id"]


def test_google_preset_validates_as_oidc_config():
    google = _preset("google")
    parsed = OidcConfig(
        issuer=google["issuer"], client_id="dummy-client", scopes=google["scopes"]
    )
    assert parsed.issuer == "https://accounts.google.com"


def test_microsoft_template_resolves_to_a_valid_oidc_config():
    microsoft = _preset("microsoft")
    issuer = microsoft["issuer_template"].format(tenant_id=SAMPLE_TENANT)
    parsed = OidcConfig(
        issuer=issuer, client_id="dummy-client", scopes=microsoft["scopes"]
    )
    assert parsed.issuer == f"https://login.microsoftonline.com/{SAMPLE_TENANT}/v2.0"


def test_exactly_one_of_issuer_and_template_per_preset():
    """The response model enforces the XOR (a bad future entry must fail at
    the route, not ship as a dead setup card), and every template placeholder
    must be resolvable from the preset's own params."""
    for preset in PROVIDER_PRESETS:
        assert (preset["issuer"] is None) != (
            preset["issuer_template"] is None
        ), preset["id"]
        if preset["issuer_template"] is not None:
            placeholders = set(re.findall(r"{(\w+)}", preset["issuer_template"]))
            assert placeholders == {
                p["key"] for p in preset["params"]
            }, preset["id"]


def test_preset_model_rejects_issuer_and_template_both_unset():
    base = {
        "id": "broken", "name": "Broken", "kind": "oidc",
        "scopes": "openid", "default_slug": "broken", "posture": "open",
        "setup_url": "https://example.com", "notes": "n",
    }
    with pytest.raises(ValidationError):
        ProviderPresetOut.model_validate(base)  # neither set
    with pytest.raises(ValidationError):
        ProviderPresetOut.model_validate(  # both set
            base
            | {"issuer": "https://a.example", "issuer_template": "https://{x}"}
        )


def test_microsoft_tenant_pattern_wants_the_guid_not_a_domain():
    """ADR-0024: Entra's discovery document advertises the GUID-form issuer,
    so a domain-form tenant would fail issuer validation at sign-in — the
    pattern rejects it up front."""
    param = _preset("microsoft")["params"][0]
    assert re.match(param["pattern"], SAMPLE_TENANT)
    assert re.match(param["pattern"], param["placeholder"])
    assert re.match(param["pattern"], "contoso.com") is None
    assert re.match(param["pattern"], "contoso.onmicrosoft.com") is None


# --- brand derivation ----------------------------------------------------------


def test_brand_google_exact_issuer():
    assert (
        brand_for_provider("oidc", {"issuer": "https://accounts.google.com"})
        == "google"
    )


def test_brand_tolerates_a_trailing_slash():
    """The admin write path rstrips the issuer, but a hand-edited row may not
    have gone through it — the derivation must not care."""
    assert (
        brand_for_provider("oidc", {"issuer": "https://accounts.google.com/"})
        == "google"
    )


def test_brand_microsoft_is_a_prefix_match():
    # Any tenant brands as Microsoft — the tenant GUID varies per install.
    issuer = f"https://login.microsoftonline.com/{SAMPLE_TENANT}/v2.0"
    assert brand_for_provider("oidc", {"issuer": issuer}) == "microsoft"


def test_brand_unrelated_issuer_is_none():
    assert brand_for_provider("oidc", {"issuer": "https://idp.example.com"}) is None


def test_brand_non_oidc_kind_is_none():
    """A SAML provider is never branded, even at a lookalike issuer — brand is
    an OIDC-issuer concept."""
    assert (
        brand_for_provider("saml", {"issuer": "https://accounts.google.com"}) is None
    )


@pytest.mark.parametrize("config", [{}, {"issuer": 123}, {"issuer": None}])
def test_brand_never_raises_on_malformed_config(config):
    """Runs on the public login-page path against the untrusted JSON column —
    a drifted row must degrade to an unbranded button, not a 500."""
    assert brand_for_provider("oidc", config) is None


# --- end to end: the public list carries the derived brand ---------------------


async def _create_enabled_provider(client, admin, *, slug, name, issuer) -> dict:
    resp = await client.post(
        "/api/admin/auth-providers",
        json={
            "kind": "oidc",
            "name": name,
            "slug": slug,
            "posture": "open",
            "config": {"issuer": issuer, "client_id": "client-123"},
            "enabled": True,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_public_list_brands_by_stored_issuer(client, no_issuer_probe):
    """No migration, deliberately: brand is derived at read time from the
    issuer the login flow actually validates against, so it works for a
    provider configured by hand long before presets existed."""
    admin = await admin_token(client)
    await _create_enabled_provider(
        client, admin,
        slug="corp-google", name="Corp Google",
        issuer="https://accounts.google.com",
    )
    await _create_enabled_provider(
        client, admin,
        slug="other", name="Other IdP",
        issuer="https://idp.example.com",
    )

    listed = (await client.get("/api/auth/providers")).json()
    by_slug = {p["slug"]: p for p in listed}
    assert by_slug["corp-google"]["brand"] == "google"
    assert by_slug["other"]["brand"] is None
