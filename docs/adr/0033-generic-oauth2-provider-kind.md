# ADR-0033: A generic `oauth2` provider kind, with userinfo as the identity source

**Status:** Accepted
**Date:** 2026-08-19
**Architecture reference:** `ARCHITECTURE.md` §7.7 (external identity); a fourth `kind` in the ADR-0022 framework, extending ADR-0021 (OIDC) and ADR-0024 (presets).

## Context

The two most-requested identity providers for a CTF audience after Google and
Microsoft are **GitHub** and **Discord**, and neither is an OIDC provider. They
are plain OAuth 2.0:

- no `.well-known/openid-configuration` discovery document, so nothing to
  `discover()`;
- **no `id_token`** — `utils/oidc.exchange_code` rejects a token response
  without one, and `validate_id_token` is the entire identity step;
- identity instead comes from a **userinfo API call** (`GET api.github.com/user`,
  `GET discord.com/api/users/@me`) authorised by the access token, whose stable
  subject is the provider's own user id.

So the existing OIDC transport cannot serve them, and the question is what shape
the support takes. The real options:

1. **Bend the OIDC kind** — make `id_token` optional and bolt a userinfo path
   into `routers/oidc.py`. Rejected: it would weaken the OIDC transport's most
   security-critical invariant (an ID token is always present and always
   validated) for the benefit of providers that are not OIDC at all, and every
   future reader of that code would have to work out which branch they are in.
2. **A GitHub transport and a Discord transport** — two bespoke routers.
   Rejected: it is the "new protocol is a fork" pattern ADR-0022 exists to
   prevent, and the next provider (GitLab, Twitch, Keycloak-in-OAuth2-mode)
   would be a third.
3. **A generic `oauth2` kind**: one transport for the authorization-code flow,
   with the provider-specific parts — endpoint URLs and which userinfo fields
   carry identity — expressed as **configuration data**. Chosen.

## Decision

Add a fourth provider `kind`, **`oauth2`**, alongside `oidc` / `saml` / `ldap`.
It is a new `kind` in the ADR-0022 framework, not a new framework: the same
`IdentityProvider` row, the same admin CRUD, the same write-time-validate +
login-time-re-parse contract (§6), and — critically — the same
`auth.external_identity.resolve_identity`, which was already protocol-agnostic
and is **unchanged** by this work.

Three things are specific to the kind:

- **Identity comes from a server-side userinfo call, not a signed assertion.**
  There is no ID token to verify, so the trust chain is: we exchange the code at
  the configured `token_url` over TLS using our `client_secret`, then present the
  resulting access token to the configured `userinfo_url` over TLS, and treat
  that response as the identity. This is the standard OAuth2-as-authentication
  pattern and is sound **only because every leg is server-to-server**. The
  platform never accepts an access token, or a userinfo payload, from the
  browser — doing so would be the classic OAuth2 authentication flaw (a token
  minted for another client replayed into our callback). The `state` parameter
  remains the CSRF control and is single-use, exactly as in the OIDC transport.

- **A claim map, as data.** `subject_field`, `email_field`, `name_field`, and
  `email_verified_field` name which userinfo JSON keys carry identity, so a new
  provider is a preset rather than code. The subject is the provider's own user
  id (GitHub's numeric `id`, Discord's snowflake `id`), coerced to a string —
  never the email, per ADR-0021's sub-first rule.

- **Honest `email_verified`, including GitHub's second endpoint.** ADR-0022 §3
  requires that an open provider's email be believed only when the IdP asserts
  it is verified. Discord exposes a `verified` boolean on the user object
  (`email_verified_field`). GitHub does not: its profile `email` is frequently
  null or unverified, and the verified set lives at a separate endpoint. An
  optional **`emails_url`** covers that shape — when set, the transport fetches
  the list and takes the address that is both `primary` and `verified`. If no
  such address exists, the profile email is still reported for display but
  **`email_verified` is false**, so it cannot link to an existing account or
  satisfy the domain allowlist.

**PKCE is opt-in** (`use_pkce`, default off). For a confidential client the
security baseline is `state` + `client_secret` + an exact registered
`redirect_uri`; PKCE is defence in depth. It is defaulted off because this kind
must work against *arbitrary* OAuth2 servers, some of which reject unrecognised
parameters — GitHub's OAuth Apps ignore PKCE, so the GitHub preset leaves it off,
while the Discord preset turns it on.

## Consequences

- **Positive:** GitHub and Discord ship as **presets, not integrations** — and so
  do GitLab, Twitch, and any other OAuth2 provider, as pure data. The linking
  core, admission policy (#118), audit events, and the public login list all
  work unchanged, because the kind plugs in where `oidc`/`saml`/`ldap` already
  do. No migration: `IdentityProvider.kind` is a plain string column and
  `AuthLoginState`'s OIDC-specific legs are already nullable.
- **Negative / cost:** this kind has **no cryptographic assertion to verify**,
  which is a genuinely weaker primitive than OIDC's signed ID token — its
  security rests on TLS and on the flow staying server-side, and a
  misconfigured `userinfo_url` pointing somewhere attacker-controlled would be
  believed. Two mitigations: all four endpoint URLs go through the same
  https-only, SSRF-blocking egress check the OIDC issuer uses (ADR-0013 lane),
  and the built-in presets fix the URLs so the common path involves no
  hand-typed endpoint at all. Operators configuring a custom OAuth2 provider are
  trusting those URLs, and the ADR says so rather than implying parity with OIDC.
  The claim map is also more configuration surface than OIDC's fixed claim names
  — the cost of serving providers with no agreed schema.
- **Forecloses nothing, but deliberately does not build:** OAuth2 **token
  refresh** and **API-scope delegation**. Flagpost wants an identity at login and
  nothing after it; the access token is used once, for the userinfo call, and
  then discarded rather than stored. Storing it would turn an authentication
  feature into a credential vault with a much larger blast radius, for no
  current use case. Likewise there is no `tid`-style organisational scoping:
  these are open, public IdPs, so admission stays the `registration_open` +
  email-domain allowlist gate (posture `open`, ADR-0022 §2), never the identity
  provider's own group/org claims.
