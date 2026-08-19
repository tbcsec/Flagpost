"""Built-in identity-provider presets for the admin "add provider" flow (ADR-0024).

Catalog-as-data, the same pattern as ``utils/automation_catalog.py``: the admin
UI renders its "Sign in with Google/Microsoft" setup cards from this module, so
adding a preset (or a field to one) is a backend-only change the UI picks up. A
preset is **form-prefill, not a write path** — creation still flows through the
existing ``POST /api/admin/auth-providers``, so a preset cannot bypass the
write-time config validation or grow its own events (ADR-0022 §6).

Presets deliberately carry **no OAuth credentials**. Every self-hosted install
registers its own app at the upstream IdP: redirect URIs differ per install,
and a client secret shipped in an open-source repo would be public. What a
preset ships is the part that is identical everywhere — issuer, scopes, and the
guidance an admin needs to produce the rest.

A preset is configuration for an **existing** protocol, never a new one. Two
kinds are represented:

- ``oidc`` — Google and Microsoft. Microsoft ships as **two** presets: a
  single-tenant one (a fixed-GUID issuer) and a multi-tenant one whose id_token
  ``iss`` is tenant-templated and validated against the signing-in tenant's own
  GUID (ADR-0032, carried in ``config.issuer_template``). The multi-tenant
  "common" authority advertises a literal ``{tenantid}`` issuer that exact
  issuer-equality would reject; the tenant-substituted validation path in
  ``utils/oidc.py`` is what admits it, scoped to providers that opt in.
- ``oauth2`` — GitHub and Discord (#193, ADR-0033). Neither speaks OIDC, so
  instead of an issuer these carry the full endpoint set plus the claim map
  naming which userinfo fields hold the subject, email and name. This is the
  payoff of the generic kind: a new OAuth2 IdP is an entry in this list, not an
  integration.
"""

from __future__ import annotations

from urllib.parse import urlsplit

_GOOGLE_ISSUER = "https://accounts.google.com"
_MICROSOFT_ISSUER_PREFIX = "https://login.microsoftonline.com/"
# Hosts whose ``authorize_url`` identifies a well-known OAuth2 provider, for the
# read-time brand derivation below.
_GITHUB_AUTHORIZE_HOST = "github.com"
_DISCORD_AUTHORIZE_HOST = "discord.com"
# The fixed multi-tenant authority (discovery is fetched here) and the template
# the per-tenant id_token ``iss`` is validated against (ADR-0032). ``{tenantid}``
# is Entra's own placeholder — the same token utils/oidc substitutes at login.
_MICROSOFT_MULTI_TENANT_AUTHORITY = "https://login.microsoftonline.com/common/v2.0"
_MICROSOFT_TENANT_ISSUER_TEMPLATE = "https://login.microsoftonline.com/{tenantid}/v2.0"

# Presets as plain dicts for the response model (schemas/auth_providers.py's
# ProviderPresetOut), mirroring build_catalog(). Exactly one of ``issuer`` /
# ``issuer_template`` is set; ``params`` are the admin inputs that resolve the
# template. The resolved issuer still passes the normal write-time validation,
# so a preset can suggest but never smuggle.
PROVIDER_PRESETS: list[dict] = [
    {
        "id": "google",
        "name": "Google",
        "kind": "oidc",
        "issuer": _GOOGLE_ISSUER,
        "issuer_template": None,
        "params": [],
        "scopes": "openid email profile",
        "default_slug": "google",
        "posture": "open",
        "setup_url": "https://console.cloud.google.com/apis/credentials",
        "notes": (
            "Create an OAuth client of the Web application type in the Google "
            "Cloud console, paste its client ID and secret here, then register "
            "the redirect URI shown after saving."
        ),
    },
    {
        "id": "microsoft",
        "name": "Microsoft",
        "kind": "oidc",
        "issuer": None,
        "issuer_template": "https://login.microsoftonline.com/{tenant_id}/v2.0",
        "params": [
            {
                "key": "tenant_id",
                "label": "Directory (tenant) ID",
                "placeholder": "00000000-0000-0000-0000-000000000000",
                "pattern": (
                    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                    "[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
                ),
                # Entra canonicalizes the tenant GUID to lowercase in its
                # discovery document and id_token ``iss``, and the issuer
                # checks in ``utils/oidc.py`` are (correctly) case-sensitive —
                # so an uppercase paste (PowerShell output, the Azure portal's
                # copy button) must be normalized before substitution, not
                # accepted verbatim to fail at first sign-in.
                "normalize": "lowercase",
                "help": (
                    "The GUID from your app registration's overview page in "
                    "Microsoft Entra. Must be the tenant ID, not a domain name "
                    "- Entra's discovery document advertises the GUID form, "
                    "and a domain-form issuer will fail validation at sign-in."
                ),
            }
        ],
        "scopes": "openid profile email",
        "default_slug": "microsoft",
        # A single-tenant directory is ADR-0022 §2's closed category: tenant
        # membership is the admission decision. An open default would apply
        # the public-registration gate (registration_open + domain allowlist)
        # to the org's own members — locking them out whenever public
        # registration is closed, which is the common setup for exactly the
        # company/campus events this preset serves.
        "posture": "closed",
        "setup_url": "https://entra.microsoft.com",
        "notes": (
            "Register a single-tenant app in Microsoft Entra, add a Web "
            "redirect URI, and create a client secret. Defaults to a closed "
            "posture: being in your tenant is the admission decision, and "
            "email stays display-only unless you mark it authoritative "
            "(ADR-0022 trust rules)."
        ),
    },
    {
        "id": "microsoft-multi-tenant",
        "name": "Microsoft (multi-tenant)",
        "kind": "oidc",
        # The fixed multi-tenant *authority* — discovery is fetched here. Unlike
        # the single-tenant preset there is no tenant to fill in, so `issuer` is
        # fixed and `params` empty; the per-tenant issuer the token actually
        # carries is validated via `config_issuer_template` (ADR-0032).
        "issuer": _MICROSOFT_MULTI_TENANT_AUTHORITY,
        "issuer_template": None,
        "config_issuer_template": _MICROSOFT_TENANT_ISSUER_TEMPLATE,
        "params": [],
        "scopes": "openid profile email",
        "default_slug": "microsoft",
        # `common` trusts *every* Entra tenant on Earth for authentication, so
        # admission has to be the public-signup gate (registration_open + the
        # email-domain allowlist), never tenant membership — hence open, the
        # opposite of the single-tenant preset. Flagpost never authorizes on the
        # `tid` claim (ADR-0021); the allowlist is the control.
        "posture": "open",
        "setup_url": "https://entra.microsoft.com",
        "notes": (
            "Register a multi-tenant app in Microsoft Entra so anyone with a "
            "work or school Microsoft account can sign in. This trusts every "
            "Entra tenant for authentication - restrict who actually gets an "
            "account with the registration email-domain allowlist, not the "
            "tenant, since Flagpost never authorizes on IdP claims "
            "(ADR-0021/0032)."
        ),
    },
    {
        "id": "github",
        "name": "GitHub",
        "kind": "oauth2",
        "issuer": None,
        "issuer_template": None,
        "config_issuer_template": None,
        "params": [],
        "oauth2": {
            "authorize_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "userinfo_url": "https://api.github.com/user",
            # read:user for the profile, user:email for the verified-address
            # list below — GitHub won't return /user/emails without it.
            "scopes": "read:user user:email",
            # A GitHub account's numeric id: stable across username changes,
            # which the login handle is not (ADR-0021 sub-first).
            "subject_field": "id",
            "email_field": "email",
            # Not "name": GitHub's display name is null for a large share of
            # accounts, while "login" (the @handle) is always present and is
            # what a CTF player expects to see on the scoreboard anyway.
            "name_field": "login",
            # GitHub asserts verification on the address list, not the profile,
            # so there is no per-profile boolean to read.
            "email_verified_field": None,
            "emails_url": "https://api.github.com/user/emails",
            # GitHub's OAuth Apps ignore PKCE, so sending it would be noise.
            "use_pkce": False,
        },
        "scopes": "read:user user:email",
        "default_slug": "github",
        # A public IdP: anyone can hold a GitHub account, so admission is the
        # site's public-signup gate (registration_open + the email-domain
        # allowlist), never mere possession of an account (ADR-0022 §2).
        "posture": "open",
        "setup_url": "https://github.com/settings/developers",
        "notes": (
            "Register an OAuth App in GitHub's developer settings, then paste "
            "its client ID and secret here and set the callback URL shown after "
            "saving. Only a primary, verified GitHub address is trusted for "
            "linking to an existing account."
        ),
    },
    {
        "id": "discord",
        "name": "Discord",
        "kind": "oauth2",
        "issuer": None,
        "issuer_template": None,
        "config_issuer_template": None,
        "params": [],
        "oauth2": {
            "authorize_url": "https://discord.com/oauth2/authorize",
            "token_url": "https://discord.com/api/oauth2/token",
            "userinfo_url": "https://discord.com/api/users/@me",
            "scopes": "identify email",
            # The account snowflake — stable across username changes.
            "subject_field": "id",
            "email_field": "email",
            # "username" is always present; "global_name" (the display name) is
            # nullable, so it would strand accounts that never set one.
            "name_field": "username",
            # Discord puts the assertion on the user object itself.
            "email_verified_field": "verified",
            "emails_url": None,
            "use_pkce": True,
        },
        "scopes": "identify email",
        "default_slug": "discord",
        "posture": "open",
        "setup_url": "https://discord.com/developers/applications",
        "notes": (
            "Create an application in the Discord developer portal, add a "
            "redirect URI under OAuth2, and paste its client ID and secret "
            "here. Discord's own verified-email flag decides whether an address "
            "is trusted for linking to an existing account."
        ),
    },
]


def brand_for_provider(kind: str, config: dict) -> str | None:
    """The well-known-IdP marker ("google" / "microsoft" / "github" /
    "discord") for a provider, or ``None`` — drives the public login page's
    button art.

    Derived from the stored config **at read time, never stored**: no
    migration, it works retroactively for a provider an admin hand-configured
    before presets existed, and it cannot drift from the endpoints the login
    flow actually uses. Which field identifies the provider depends on the kind
    — an OIDC provider is known by its issuer, a plain-OAuth2 one by the host it
    sends the browser to, since it has no issuer.

    Defensive on purpose — ``config`` is the untrusted JSON column, and this
    runs on the public login-page path, where a drifted row must stay a
    non-branded button, never a 500.
    """
    if not isinstance(config, dict):
        return None
    if kind == "oidc":
        issuer = str(config.get("issuer") or "").rstrip("/")
        if issuer == _GOOGLE_ISSUER:
            return "google"
        if issuer.startswith(_MICROSOFT_ISSUER_PREFIX):
            return "microsoft"
        return None
    if kind == "oauth2":
        # Host equality, not a prefix match: these are single fixed endpoints,
        # and a prefix test would brand `https://github.com.evil.example/…`.
        host = (urlsplit(str(config.get("authorize_url") or "")).hostname or "").lower()
        if host == _GITHUB_AUTHORIZE_HOST:
            return "github"
        if host == _DISCORD_AUTHORIZE_HOST:
            return "discord"
    return None
