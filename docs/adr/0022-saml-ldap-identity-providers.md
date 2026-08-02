# ADR-0022: SAML and LDAP identity providers — generalizing the provider model

**Status:** Proposed
**Date:** 2026-08-02
**Architecture reference:** `ARCHITECTURE.md` §7.7 (extends ADR-0021; secret
storage from ADR-0020; SSRF hardening from ADR-0013; admission gate from #118)

## Context

ADR-0021 shipped OIDC as the first external-identity provider and, deliberately,
built the seam protocol-agnostic: *"a provider resolves an external identity to a
local user"*, not "a provider is an OAuth dance". It named SAML (#100) and LDAP
(#101) as the next two protocols and required they not start "until this
framework has shipped and met a real provider" — which it now has (v1.2.0).

The seam is
[`auth.oidc_identity.resolve_identity`](../../backend/auth/oidc_identity.py):
given a normalized `(provider, subject, email, email_verified, claims)` it does
sub-first linking, the #118 admission gate, JIT-provision-as-Participant, and the
break-glass unusable-password-hash. Two supporting pieces are already generic:
the `manage_auth_providers` permission and the `auth_provider.{created,updated,deleted}`
events (not named `oidc.*`).

The questions here were never about the session contract or the *downstream* of
identity resolution — those are settled. They were:

1. **How one provider model holds three unlike kinds**, given
   [`UserExternalIdentity.provider_id`](../../backend/models/oidc.py) FKs
   `oidc_providers` and the kinds' configuration barely overlaps.
2. **Where each transport plugs in** — OIDC and SAML are browser-redirect
   federations; LDAP is a credential *bind* with no redirect and the user's
   directory password passing through our server.
3. **What "verified" means per protocol.** This is the subtle one. `resolve_identity`
   encodes OIDC's trust model — link/admit on a `email_verified: true` claim — and
   that model does *not* transfer: a directory bind proves control of a credential,
   not ownership of the `mail` attribute in the entry, and a SAML `NameID` often
   carries no email at all. So `resolve_identity` is **not** reused unchanged; the
   trust model has to become per-provider.
4. **The protocol-specific security surfaces**: XML-signature/XSW for SAML,
   cleartext credential transit for LDAP.

## Decision

### 1. One `identity_providers` table, discriminated by `kind`

Replace `oidc_providers` with a site-wide `identity_providers` table:

- **Typed shared columns:** `id`, `kind` (`"oidc" | "saml" | "ldap"`),
  `posture` (`"open" | "closed"`, see §2), `name`, `slug`, `enabled`, timestamps.
- **One `secret` column** (`EncryptedString`, nullable). Each kind has exactly
  one retrievable secret — OIDC client secret, SAML SP private key, LDAP bind
  password — so a single encrypted column, interpreted per kind, beats a sprawl
  of mostly-null columns. Encrypted not hashed (ADR-0020), write-only over the
  API exactly like `client_secret` today.
- **A `config` JSON column** for the non-secret kind-specific rest, validated at
  the API boundary by a Pydantic **discriminated union on `kind`** (the generic-
  `JSON`-portable tradeoff ADR-0006 accepts elsewhere).

**Migration (the one production-data change in this work).**
`user_external_identities.provider_id` and the renamed in-flight-state table's
`provider_id` repoint to `identity_providers.id`. On SQLite this is **not** an
in-place FK repoint — under `render_as_batch` (ADR-0006) it is a table rebuild,
ordered: create `identity_providers` → backfill from `oidc_providers`
(`kind="oidc"`, `posture="open"`, `issuer`/`client_id`/`scopes` folded into
`config`, `client_secret` into `secret`) → rebuild the child tables with the new
FK → drop `oidc_providers`. The secret is copied as a **raw column value at the
SQL level, never read through the ORM** (which would decrypt, and needlessly
couple the migration to the encryption key) — `EncryptedString`'s read path keys
off the `gAAAAA` prefix, so a straight ciphertext copy round-trips. The rename
touches [`models/__init__.py`](../../backend/models/__init__.py) (which must
import every model) and every importer (`routers/oidc*.py`, `auth/oidc_identity.py`,
`utils/oidc.py`) in lockstep, or the schema build drops a table. A downgrade path
is required — real deployments, a failed upgrade must reverse. CI's Postgres job
**and** a local SQLite `render_as_batch` run must both exercise it.

Rejected: sibling per-kind tables with a polymorphic link (drops the clean
identity-link FK, unions every "list providers"). Rejected: class-table
inheritance (cleaner typing, but three extra tables and a join per read, and it
still migrates the OIDC rows).

### 2. Provider trust posture: `open` vs `closed`

The #118 admission gate (registration-open + email-domain allowlist) exists to
stop a **public** IdP — Google, GitHub — from letting anyone with such an account
self-provision. That is a control on *public self-service registration*. An
admin-configured **directory or enterprise IdP** (a university's Shibboleth, a
corporate AD) is a different thing: the admin has vouched for the whole
population, and being *in the directory* is itself the authorization to enter.
Applying a public-signup domain filter to it is a category error, and — because
directory email is unverified (§Context.3) — would either lock the whole
directory out (allowlist on, no verified email) or invite hijack (force
`email_verified=true` to pass it).

So each provider carries a **posture**:

- **`open`** (default for OIDC public IdPs): the #118 site gate applies —
  registration-open + email allowlist govern whether a new identity may
  provision, exactly as today.
- **`closed`** (default and only option for SAML/LDAP): the provider being
  `enabled` **is** the admission decision; the site public-signup gate does
  **not** apply. Narrowing a closed provider further (e.g. one department inside
  an eduGAIN federation) is a per-provider allowlist — deferred, not v1.

And email linking becomes posture-aware:

- An **`open`** provider links a first login to an existing local account by
  email only on `email_verified: true` from the IdP — unchanged.
- A **`closed`** provider is **subject-only by default**: its email is captured
  for display/audit but never used to claim a pre-existing account, because the
  directory's `mail` attribute is not proof of address ownership. An admin who
  knows their directory verifies email may set a per-provider
  `email_is_authoritative` flag to re-enable email linking; it is **off by
  default**, which closes the C1 hijack outright. In the common enterprise case
  there are no pre-existing local accounts to link anyway (bar the ADR-0017
  owner), so subject-only JIT is the norm.

### 3. `resolve_identity` becomes posture-aware (a deliberate contract change)

`resolve_identity` takes the provider (now carrying `kind` + `posture` +
`email_is_authoritative`) and branches:

- **Step-2 email linking** runs only when the provider's email is trusted:
  `open` + IdP `email_verified`, or `closed` + `email_is_authoritative`.
  Otherwise it is skipped (subject-only).
- **The admission gate** applies only to `open` providers. A `closed` provider
  reaching JIT is admitted by virtue of having authenticated against an enabled
  provider.
- The transports set `email_verified` honestly: OIDC from the claim (already
  strict, #118); SAML/LDAP to the provider's `email_is_authoritative` (default
  `false`), so a directory address is never silently treated as verified.

This is the point ADR-0021's "seam is protocol-agnostic" was always going to
cost: the *shape* (resolve an external identity to a local user) is stable, but
the *trust rules* are per-provider and now live explicitly in the signature
rather than implicitly assuming OIDC. `_emit_linked` and the internal helpers
generalize off `OidcProvider` to the new type at the same time.

### 4. SAML — SP-initiated redirect + assertion

A login endpoint redirects to the IdP; an **Assertion Consumer Service (ACS)**
POST endpoint receives the signed assertion (replacing OIDC's callback GET),
reusing the in-flight table for `RelayState` + `InResponseTo`. It maps the
assertion `NameID` → `subject`, attributes → email/display-name, then calls
`resolve_identity`. Library: **python3-saml** (OneLogin) — SP-focused, XSW-hardened,
smaller than pysaml2 for one SP. We do not hand-roll XML or signatures.

**SP-initiated only** for v1: an unsolicited (IdP-initiated) assertion has no
`InResponseTo`, trading away the CSRF/replay defense; deferred.

Mandatory, enforced and tested:

- Reject any assertion whose signature is absent or invalid; validate signature
  **before** trusting content. XSW and XXE/DTD defenses on (verified by a known
  XSW-payload test).
- Validate `Conditions` (`NotBefore`/`NotOnOrAfter` with a small **configurable
  clock-skew** tolerance, or IdP drift breaks every login; `AudienceRestriction`)
  and single-use assertion IDs (replay). `InResponseTo` must match an in-flight
  request we issued.
- **Require a persistent/stable `NameID`** (reject `transient` — it changes each
  login and would JIT a fresh account every time; the SAML analogue of "not the
  DN" below).
- The **ACS endpoint is a cross-site top-level POST**: CSRF-exempt, requires no
  session cookie inbound, and lives outside the `(app)` shell / `SetupGuard`
  (like the other auth screens). Its terminal handshake mirrors OIDC's — set the
  refresh cookie and 302 to the frontend, which calls `/api/auth/refresh` so no
  token rides a URL — and carries `set-cookie` across the `RedirectResponse`
  explicitly, as the OIDC callback already must.
- Expose an **SP metadata GET endpoint** (ACS URL + SP cert), so an IdP admin can
  consume it instead of hand-transcribing. SP private key is `EncryptedString`;
  a server-side IdP-metadata fetch goes through the ADR-0013 SSRF blocklist.

### 5. LDAP — credential bind inside the local login route

LDAP has no redirect, so it plugs into
[`POST /api/auth/login`](../../backend/routers/auth.py), which is restructured so
that a failed local password verify no longer immediately 401s but first attempts
the directory. The full sequence, spelled out because the natural "bind → issue"
path omits a load-bearing step:

1. Throttle on the identifier (unchanged, and it stays **before** the bind so the
   directory can't be probed unthrottled).
2. Local verify first — the ADR-0017 owner and any real-password account
   short-circuit here and never touch the directory. (A returning LDAP user
   exists locally with the unusable hash, so their local verify harmlessly fails
   and falls through.)
3. On local failure, for each enabled LDAP provider: bind with the submitted
   credentials, with a short **bind timeout (3–5s)** run **off the event loop**
   (`asyncio.to_thread`, like the argon2 work), so a slow or down directory can't
   tie up the worker pool into a slow-loris.
4. On a successful bind: read the entry, normalize it, `resolve_identity`.
5. **`if not user.is_active: raise 403`** — load-bearing. The directory bind
   *succeeds* for a locally-banned user (the directory doesn't know about the
   ban), so the post-resolve active check is the *only* thing stopping a banned
   LDAP user from getting a session. This mirrors where the OIDC callback puts
   its `is_active` check (after `resolve_identity`, since step-1 returns a linked
   user without checking it).
6. `_issue_session`.

Library: **ldap3**. Mandatory:

- **LDAPS or StartTLS with certificate verification — always.** The user's
  password transits our server on every login; no plaintext-bind option is
  exposed.
- `subject` is a **stable directory id** (AD `objectGUID`, OpenLDAP/FreeIPA
  `entryUUID`), configurable, **never the DN** (a DN changes on an OU move).
- The **search attribute** (`uid`/`sAMAccountName`/`userPrincipalName`) is
  per-provider `config`; the **raw submitted identifier** is escaped per
  **RFC 4515** before entering the filter (LDAP injection is this surface's SQLi).
- Service-account bind password is `EncryptedString`; no anonymous auth bind.
- **Directory-only, no local-password fallback:** an LDAP user gets the unusable
  password hash like a JIT SSO user, so a directory outage means they can't log
  in until it returns — while the owner always can. Break-glass stays one uniform
  mechanism; no directory password is ever stored. The residual **timing signal**
  (a failed-local attempt now costs a bind round-trip, distinguishing
  "has-local-password" from "directory-only/nonexistent") is accepted as
  low-severity given the throttle bounds volume; perfectly equalizing it is
  impractical and not worth the complexity.

### 6. Config validated at write *and* re-parsed at login

The `config` JSON is validated by the discriminated union on write, and
**re-parsed through the same kind model on read at login** — mirroring how the
OIDC admin re-checks the issuer "again on every fetch". A provider whose stored
config is incomplete or mis-kinded (a migrated row, a stale schema, a direct DB
edit) is then a **logged skip**, not a 500 at a user's login. `enabled=True` is
refused at write unless the full config validates, so "enabled but half-configured"
isn't reachable through the API. The migration asserts every copied OIDC row
round-trips the validator.

### 7. What does not change, and operational notes

RBAC stays 100% local — no provider of any kind grants a permission, and
directory-group → role mapping stays foreclosed (ADR-0021/ADR-0004). Subject is
authoritative once linked; email is never the primary key. `_issue_session`,
refresh cookies, WebSocket auth and API tokens are untouched. The
`auth_provider.*` and `identity.linked` events cover the new kinds with no new
event types.

- The provider button list (`GET …/providers`) must **exclude `kind=ldap`** — LDAP
  is the ordinary username/password form, not a "Sign in with…" redirect, so a
  button would be dead.
- The renamed table must **stay out of the backup `SPECS` allowlist**
  (exclusion-by-omission, like `oidc_providers` today) — it now also holds SAML
  SP keys and LDAP bind passwords, per-install secrets encrypted with a key the
  destination install won't share, so it must never travel in a portable backup.

## Consequences

- **Positive:** one provider abstraction, one admin CRUD surface
  (`/api/admin/auth-providers`), one identity link table, one break-glass
  mechanism; a fourth protocol later is a new `kind` + transport, not a
  subsystem. The posture split gives directory logins a *correct* trust model
  instead of forcing OIDC's onto them. Session contract and RBAC genuinely
  untouched; the hard protocol parts stay inside maintained libraries.
- **Negative / cost:** `resolve_identity` gains real per-provider branching — the
  price of honesty about trust that ADR-0021 deferred. Two unforgiving security
  surfaces: SAML XML-signature validation (a shortcut is a vulnerability, and
  python3-saml pulls native `xmlsec`/`libxml2` into the image), and LDAP putting
  a live credential through our process on every bind (the TLS, filter-escaping,
  bind-timeout and off-loop requirements are all load-bearing, and `/login` grows
  a directory-outage path). The unified table needs the one production-data
  migration, a table rebuild on SQLite with a raw-ciphertext secret copy and a
  lockstep model rename — verified on both engines with a downgrade.
- **Forecloses (for v1):** IdP-initiated SAML (no `InResponseTo`; a likely
  fast-follow), per-provider federation allowlists, multiple SPs / per-competition
  providers (auth is install-level, ADR-0021), and directory group synchronization.
