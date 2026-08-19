# ADR-0032: Multi-tenant Entra issuer validation via a tenant-substituted issuer template

**Status:** Accepted
**Date:** 2026-08-19
**Architecture reference:** `ARCHITECTURE.md` §7.7 (external identity); resolves the multi-tenant Entra deferral in ADR-0024; extends the OIDC mechanics of ADR-0021/0022.

## Context

The Microsoft preset shipped in ADR-0024 is **single-tenant only**: an admin
configures one specific Entra directory, whose issuer is a fixed GUID
(`https://login.microsoftonline.com/<tenant-guid>/v2.0`). The next ask is
"sign in with *any* Microsoft account" — the multi-tenant authorities `common`
and `organizations` — which ADR-0024 explicitly deferred as its own decision.

Multi-tenant Entra is still ordinary OIDC, but its issuer is **templated**, and
that breaks the two exact-string issuer checks that are the core of OIDC token
trust (§7.7, ADR-0021):

1. **Discovery equality** (`utils/oidc.discover`). The `common` discovery
   document at `.../common/v2.0/.well-known/openid-configuration` advertises the
   literal string `https://login.microsoftonline.com/{tenantid}/v2.0` — a
   placeholder, not a concrete issuer — so `advertised != configured` and
   discovery is dead on arrival.
2. **Token issuer match** (`utils/oidc.validate_id_token`, `jwt.decode(...,
   issuer=...)`). The id_token's real `iss` carries the **signing-in user's**
   tenant GUID, not `common`, so PyJWT raises `InvalidIssuerError`.

This is the well-known "Azure AD multi-tenant issuer validation" problem; every
OIDC library special-cases it. The real options were:

- **Relax the checks globally** (prefix/substring match on the Microsoft host).
  Rejected: it weakens issuer validation for *every* provider to serve one, and
  a host-prefix match is exactly the kind of shortcut ADR-0021 warns is a
  vulnerability rather than a bug.
- **A Microsoft-specific validation mode** (`issuer_validation:
  "azure_multi_tenant"`) with the template and host hardcoded in code.
  Safe, but couples the generic OIDC config schema to one vendor and doesn't
  generalize — the opposite of ADR-0021/0022's "a new capability is data, not a
  fork" grain.
- **A generic tenant-substituted issuer template** validated structurally at
  write time and bound to the token's own tenant claim at login. Chosen.

## Decision

`OidcConfig` gains an optional `issuer_template` (default `None`). When it is
**unset — every existing and single-tenant provider — nothing changes**: the
exact-equality checks run exactly as before. When it is set, the provider is a
tenant-templated issuer and two things change, scoped to that provider only:

- **Discovery** accepts an advertised issuer that equals *either* the configured
  authority (`.../common/v2.0`) *or* the template
  (`.../{tenantid}/v2.0`) — Entra advertises the latter verbatim.
- **Token validation** no longer asks PyJWT to match `iss` against a fixed
  string. Instead it substitutes the token's **own `tid` claim** into the
  template and requires `iss` to equal the result, with `tid` constrained to a
  GUID: `iss == issuer_template.replace("{tenantid}", tid)`. Signature (`common`
  JWKS), `aud`, `exp`/`iat`, and `nonce` are validated unchanged.

The template is **not free-form admin input in practice** — it is validated at
write time (https, exactly one `{tenantid}` placeholder, the placeholder in the
path and never the host, and the same host as the discovery authority) and is
supplied by a new built-in **"Microsoft (multi-tenant)"** preset so an admin
never hand-types it. The preset defaults to **`open`** posture: `common` trusts
every Entra tenant on Earth for *authentication*, so admission is the existing
public-signup gate (`registration_open` + email-domain allowlist), never the
`tid` claim.

## Consequences

- **Positive:** multi-tenant Entra becomes configuration, not a protocol fork —
  `discover()`/`validate_id_token()` gain one optional argument and the change
  is a JSON-column field, so **no migration**. The `iss`↔`tid` binding is the
  standard, documented Entra hardening: a token is attributed to the tenant that
  actually signed it, and a token minted for tenant A cannot present tenant B's
  identity. Single-tenant and every non-Microsoft OIDC provider are byte-for-byte
  unchanged, because the whole mechanism is gated on `issuer_template` being set.
- **Negative / cost:** the templated branch validates `iss` *by hand* rather than
  delegating to PyJWT, so the manual check (GUID `tid`, exact substituted match)
  is now load-bearing and must be kept as strict as the library call it replaces
  — it carries its own tests for a non-GUID tenant, a mismatched host/path, and a
  single-tenant regression. The `{tenantid}` placeholder is Entra's spelling and
  the `tid` claim is Microsoft's; the field is generic in shape but Entra-shaped
  in practice, which the docstring says plainly rather than pretending otherwise.
- **Forecloses nothing, but deliberately does not build:** a `tid` **allowlist**.
  Flagpost ignores IdP claims for authorization by design (ADR-0021) — organizational
  scoping rides the email-domain allowlist, not `tid`/`hd` — so gating admission on
  `tid` would move an authorization decision outside the platform's own audit log.
  It stays available as a future opt-in if a concrete need lands. `consumers`
  (personal Microsoft accounts) is not multi-tenant in this sense: it advertises a
  fixed MSA-tenant GUID, so it is served by the existing single-tenant path, not
  this one.
