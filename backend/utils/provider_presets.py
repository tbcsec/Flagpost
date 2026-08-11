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

Both presets are plain OIDC (kind ``"oidc"``): a preset is configuration for an
existing protocol, never a new one. Microsoft is **single-tenant only** — the
multi-tenant "common" endpoint advertises a literal ``{tenantid}`` template as
its issuer, which the strict issuer-equality checks in ``utils/oidc.py``
correctly reject; supporting it is its own decision (ADR-0024), not a preset.
"""

from __future__ import annotations

_GOOGLE_ISSUER = "https://accounts.google.com"
_MICROSOFT_ISSUER_PREFIX = "https://login.microsoftonline.com/"

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
]


def brand_for_provider(kind: str, config: dict) -> str | None:
    """The well-known-IdP marker ("google" / "microsoft") for a provider, or
    ``None`` — drives the public login page's button art.

    Derived from the stored issuer **at read time, never stored**: no
    migration, it works retroactively for a provider an admin hand-configured
    before presets existed, and it cannot drift from the issuer the login flow
    actually validates against.

    Defensive on purpose — ``config`` is the untrusted JSON column, and this
    runs on the public login-page path, where a drifted row must stay a
    non-branded button, never a 500.
    """
    if kind != "oidc" or not isinstance(config, dict):
        return None
    issuer = str(config.get("issuer") or "").rstrip("/")
    if issuer == _GOOGLE_ISSUER:
        return "google"
    if issuer.startswith(_MICROSOFT_ISSUER_PREFIX):
        return "microsoft"
    return None
