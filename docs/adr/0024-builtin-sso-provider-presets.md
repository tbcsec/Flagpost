# ADR-0024: Built-in SSO provider presets — configuration, never credentials

**Status:** Accepted
**Date:** 2026-08-11
**Architecture reference:** `ARCHITECTURE.md` §7.7 (extends ADR-0021/ADR-0022)

## Context

Setting up "Sign in with Google/Microsoft" requires hand-authoring OIDC config
(issuer, scopes) that is identical on every install, plus per-install pieces
(client ID/secret, redirect URI) that cannot be shared. Admins get the
universal part wrong — especially Entra, where the issuer embeds a tenant ID
and a plausible-looking domain-form issuer fails validation at sign-in. The
real options were: ship presets as data feeding the existing provider CRUD;
ship pre-registered OAuth apps (how hosted SaaS does it); or add a dedicated
"create from preset" endpoint. A second question was whether the login page
should know a provider is Google/Microsoft (for button art) via a stored
column or a derived value.

## Decision

- **Presets ship configuration defaults, never OAuth credentials.** Each
  self-hosted install registers its own upstream app: redirect URIs differ per
  install, and a shared secret shipped in an open-source repo would be public.
- **Presets are data in one catalog module** (`utils/provider_presets.py`,
  the `automation_catalog.py` pattern) served read-only from
  `GET /api/admin/auth-providers/presets`. Creation still flows through the
  existing provider CRUD — a preset is form-prefill, so no new write path and
  no new events.
- **`brand` is derived from the stored issuer at read time, not stored.** No
  migration, it works retroactively for hand-configured providers, and it
  cannot drift from the issuer the login flow actually validates against.
- **Microsoft is single-tenant only for now.** The multi-tenant "common"
  endpoint advertises a templated issuer (`{tenantid}`) that the strict
  issuer-equality checks in `utils/oidc.py` (`discover()` and
  `validate_id_token()`) correctly reject; supporting it means deliberately
  hardening that validation, which is its own decision, not a preset.
- **The tenant must be the GUID, not a domain name** — Entra's discovery
  document advertises the GUID-form issuer, so a domain-form issuer fails the
  same equality checks. The GUID is also **lowercased at substitution**
  (`normalize: "lowercase"` on the preset param): Entra canonicalizes it to
  lowercase in the discovery document and `iss` claim, the issuer checks are
  case-sensitive, and an uppercase paste (PowerShell, the portal's copy
  button) would otherwise save fine and fail at first sign-in — the exact
  silent misconfiguration presets exist to prevent.
- **Postures follow ADR-0022 §2's classification, per preset.** Google is
  `open`: a public IdP, so the public-registration gate (`registration_open`
  + the domain allowlist) applies to JIT sign-ups. Microsoft single-tenant
  defaults to `closed`: an admin-configured org directory is exactly the
  closed category — tenant membership *is* the admission decision — and an
  open default would apply the public-registration gate to the org's own
  members, locking them out whenever public registration is closed (the
  common setup for the company/campus events this preset serves). The admin
  can still flip it.

## Consequences

- **Positive:** the two most-requested IdPs become fill-in-two-fields setups;
  the catalog-as-data shape means a third preset (Okta, GitLab…) is a
  backend-only data change; the write path, validation, posture rules and
  event vocabulary are untouched.
- **Negative / cost:** presets encode upstream facts (issuer URLs, console
  URLs, Entra's GUID canonicalization and `email_verified` behavior) that can
  rot silently — nothing in CI talks to Google or Microsoft. Under the closed
  default, a Microsoft user's email is display-only unless the admin marks it
  authoritative; if the admin flips the provider to open, Entra rarely asserts
  `email_verified`, so first-time sign-ins JIT-create new accounts rather
  than auto-linking by email (ADR-0022 trust rules). The preset's notes say
  so rather than pretending otherwise.
- **Forecloses:** shipping a hosted-style "works out of the box" OAuth app,
  and (for now) multi-tenant Entra. Both could return as their own decisions.
