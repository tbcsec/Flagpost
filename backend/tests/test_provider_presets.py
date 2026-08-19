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
    OAuth2Config,
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
    assert [p["id"] for p in body] == [
        "google",
        "microsoft",
        "microsoft-multi-tenant",
        "github",
        "discord",
    ]
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


def test_multi_tenant_preset_is_open_and_tenant_templated():
    """ADR-0032: the multi-tenant preset fixes the `common` authority and carries
    the per-tenant validation template. Open posture because `common` trusts every
    Entra tenant — admission is the email-domain allowlist, not the tenant."""
    mt = _preset("microsoft-multi-tenant")
    assert mt["kind"] == "oidc"
    assert mt["issuer"] == "https://login.microsoftonline.com/common/v2.0"
    assert mt["issuer_template"] is None  # no form-fill; the authority is fixed
    assert (
        mt["config_issuer_template"]
        == "https://login.microsoftonline.com/{tenantid}/v2.0"
    )
    assert mt["params"] == []
    assert mt["posture"] == "open"
    # Brands as Microsoft off the common authority (the prefix match).
    assert brand_for_provider("oidc", {"issuer": mt["issuer"]}) == "microsoft"


def test_multi_tenant_preset_config_round_trips_the_write_path():
    """The config the preset prefills — the common authority plus the tenant
    template — must be exactly what the create API's OidcConfig accepts, or the
    setup card is a dead end (ADR-0032)."""
    mt = _preset("microsoft-multi-tenant")
    parsed = OidcConfig(
        issuer=mt["issuer"],
        client_id="dummy-client",
        scopes=mt["scopes"],
        issuer_template=mt["config_issuer_template"],
    )
    assert parsed.issuer == "https://login.microsoftonline.com/common/v2.0"
    assert parsed.issuer_template == "https://login.microsoftonline.com/{tenantid}/v2.0"


def test_exactly_one_of_issuer_and_template_per_oidc_preset():
    """The response model enforces the XOR (a bad future entry must fail at
    the route, not ship as a dead setup card), and every template placeholder
    must be resolvable from the preset's own params. OIDC-only: an `oauth2`
    preset has no issuer at all and carries an `oauth2` block instead."""
    for preset in PROVIDER_PRESETS:
        if preset["kind"] != "oidc":
            continue
        assert (preset["issuer"] is None) != (
            preset["issuer_template"] is None
        ), preset["id"]
        if preset["issuer_template"] is not None:
            placeholders = set(re.findall(r"{(\w+)}", preset["issuer_template"]))
            assert placeholders == {
                p["key"] for p in preset["params"]
            }, preset["id"]


@pytest.mark.parametrize("preset_id", ["github", "discord"])
def test_oauth2_preset_config_round_trips_the_write_path(preset_id):
    """A preset whose config the create API would refuse is a dead card. This
    is the oauth2 analogue of the OIDC issuer round-trip above."""
    preset = _preset(preset_id)
    assert preset["kind"] == "oauth2"
    # No issuer — that's the whole point of the kind (ADR-0033).
    assert preset["issuer"] is None and preset["issuer_template"] is None
    parsed = OAuth2Config(client_id="dummy-client", **preset["oauth2"])
    assert parsed.authorize_url.startswith("https://")
    assert parsed.subject_field == "id"


def test_github_preset_reads_verified_addresses_from_the_second_endpoint():
    """GitHub asserts verification on /user/emails, not the profile — so the
    preset must carry the emails URL and the scope that unlocks it, or every
    GitHub sign-in would land as unverified (ADR-0022 §3)."""
    github = _preset("github")["oauth2"]
    assert github["emails_url"] == "https://api.github.com/user/emails"
    assert "user:email" in github["scopes"]
    assert github["email_verified_field"] is None
    # GitHub's display name is null for most accounts; the handle always exists.
    assert github["name_field"] == "login"
    # GitHub's OAuth Apps ignore PKCE.
    assert github["use_pkce"] is False


def test_discord_preset_uses_its_own_verified_flag():
    discord = _preset("discord")["oauth2"]
    assert discord["email_verified_field"] == "verified"
    assert discord["emails_url"] is None
    assert discord["use_pkce"] is True


def test_public_oauth2_presets_are_open_posture():
    """Anyone can hold a GitHub/Discord account, so admission has to be the
    site's public-signup gate, never possession of an account (ADR-0022 §2)."""
    for preset_id in ("github", "discord"):
        assert _preset(preset_id)["posture"] == "open"


def test_brand_derives_from_the_oauth2_authorize_host():
    assert (
        brand_for_provider("oauth2", {"authorize_url": "https://github.com/login/oauth/authorize"})
        == "github"
    )
    assert (
        brand_for_provider("oauth2", {"authorize_url": "https://discord.com/oauth2/authorize"})
        == "discord"
    )


def test_brand_oauth2_requires_host_equality_not_a_prefix():
    """A prefix match would brand an attacker-controlled lookalike host."""
    assert (
        brand_for_provider(
            "oauth2",
            {"authorize_url": "https://github.com.evil.example/login/oauth/authorize"},
        )
        is None
    )


def test_preset_model_rejects_a_mismatched_config_block():
    """Each kind must carry exactly the block it can use — a catalog entry that
    mixes them should fail loudly at the route, not ship as a broken card."""
    oauth2_block = _preset("github")["oauth2"]
    base = {
        "id": "broken", "name": "Broken", "scopes": "openid",
        "default_slug": "broken", "posture": "open",
        "setup_url": "https://example.com", "notes": "n",
    }
    with pytest.raises(ValidationError):  # oauth2 preset with no oauth2 block
        ProviderPresetOut.model_validate(base | {"kind": "oauth2"})
    with pytest.raises(ValidationError):  # oauth2 preset carrying an issuer
        ProviderPresetOut.model_validate(
            base
            | {
                "kind": "oauth2",
                "oauth2": oauth2_block,
                "issuer": "https://a.example",
            }
        )
    with pytest.raises(ValidationError):  # oidc preset carrying an oauth2 block
        ProviderPresetOut.model_validate(
            base
            | {
                "kind": "oidc",
                "issuer": "https://a.example",
                "oauth2": oauth2_block,
            }
        )
    with pytest.raises(ValidationError):  # a kind with no defined block at all
        ProviderPresetOut.model_validate(base | {"kind": "saml"})


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
