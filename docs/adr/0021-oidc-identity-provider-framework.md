# ADR-0021: External identity via OIDC, with local login as break-glass

**Status:** Accepted
**Date:** 2026-07-31
**Architecture reference:** `ARCHITECTURE.md` §7.7 (extends ADR-0003; policy for
secret storage from ADR-0020)

## Context

Local password auth has been the only way in since Tier 0, and
`docs/ROADMAP.md` deferred external identity ("LDAP, SAML, OAuth") past public
release. That deferral has now been overtaken: organisations running a CTF on
their own infrastructure want their existing directory to decide who gets in,
and issue #58 makes it the last feature of v1.2.0.

ADR-0003 anticipated exactly this — it recorded that SSO providers would "plug
into this same *produces a `current_user` and a session* contract rather than
requiring a second auth path later". So the question here is not whether to
change the session contract (we don't), but what shape the provider layer takes
and how an external identity is allowed to become — or attach to — a local
account.

Three forks were real:

1. **Which protocol first.** "SSO" covers OIDC/OAuth2, SAML and LDAP. They are
   not one feature: OIDC and SAML are both browser-redirect federations, while
   LDAP is a credential *bind* where the user's directory password passes
   through our server. Building all three at once would fix an abstraction
   before any of it had met a real IdP.
2. **How an external identity maps to a local account.** Matching on email is
   the obvious answer and the dangerous one: an IdP that returns an
   unverified — or recycled — address would become a way to claim somebody
   else's existing account.
3. **Whether local login survives.** If SSO is the way in, leaving password
   login fully open undermines the point; closing it entirely means a broken or
   misconfigured IdP locks every administrator out of their own platform, with
   no path back in.

## Decision

**OIDC/OAuth2 only for this phase.** SAML (#100) and LDAP (#101) are separate
issues on later milestones and must not start until this framework has shipped
and met a real provider. The provider abstraction deliberately does **not**
assume every provider is redirect-based — LDAP has no callback, no `state`, no
PKCE and no `sub`, so the seam is "a provider resolves an external identity to a
local user", not "a provider is an OAuth dance".

**Providers are site-wide config on a required-core module, not per-competition
toggles.** Authentication is a property of the install, not of a competition;
`competition_modules` (§11.3) has no site-scoped equivalent and inventing one
for this would change §11 for every future feature. The `sso` module is always
mounted and each provider row carries its own `enabled` flag, mirroring how
`site_settings` is required-core with admin-gated configuration.

**Identity resolution is subject-first, with a verified-email fallback used only
on first contact.** A returning user is matched on `(provider_id, sub)` — the
IdP's stable subject. Only a *first* login from a provider falls back to
matching an existing local account by email, and only when the IdP asserts
`email_verified: true`. Anything else JIT-creates a new account.

**JIT-provisioned users get the Participant role and nothing more**, mirroring
the rule that public registration never grants above Participant (ADR-0017).
External identity answers *who you are*; RBAC (§7, ADR-0004) remains the only
thing that decides what you may do.

**Local login survives as break-glass, structurally rather than by policy.** A
JIT-provisioned SSO user is given a random, never-disclosed password hash, so
they *cannot* use the local form — there is no password for them to know. No UI
restriction is needed and none is enforced server-side. Accounts that do have a
real password (notably the first-run owner from ADR-0017) keep working, which is
precisely the account an operator needs when the IdP is down or misconfigured.

**The client secret is stored encrypted, not plaintext.** Per ADR-0020, it must
be *retrieved* to authenticate to the token endpoint, so it is encrypted rather
than hashed. This ADR therefore also introduces the general encrypted-column
facility (`utils/crypto.EncryptedString`), keyed by the ADR-0019
derive-and-persist pattern; #109 adopts it for the remaining plaintext secrets.

## Consequences

- **Positive:** the session contract is untouched — the callback issues a
  session through the same `_issue_session` seam password login uses, so
  everything downstream (refresh, WebSocket auth, API tokens) works unchanged.
  RBAC is genuinely unaffected: no provider can grant a permission. The
  break-glass property falls out of the data model instead of relying on an
  admin remembering to keep a local account. Encrypted secrets arrive as a
  reusable facility rather than a one-off.
- **Negative / cost:** we now maintain OIDC protocol code (discovery, JWKS
  rotation, PKCE, ID-token validation) — a well-specified but unforgiving
  surface where a validation shortcut is a real vulnerability, not a bug. Admin
  URLs are fetched server-side, so the SSRF hardening built for webhooks
  (ADR-0013) has to be applied here too. Encryption introduces a key whose loss
  makes stored secrets unrecoverable; they must be re-entered, and the key file
  belongs on the same backed-up volume as the JWT secret.
- **Forecloses:** IdP-driven authorisation. Group/role claims are deliberately
  ignored — mapping them onto Flagpost roles would put permission assignment in
  a system outside the platform's audit log, which ADR-0004 exists to prevent.
  It also forecloses making email the primary identity key: `sub` is
  authoritative once linked, so an address changing at the IdP follows the user
  rather than silently minting or hijacking an account.
