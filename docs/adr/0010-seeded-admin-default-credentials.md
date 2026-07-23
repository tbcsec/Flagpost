# ADR-0010: Seed a default administrator with default credentials

**Status:** Superseded by [ADR-0017](0017-first-run-setup-wizard.md)
**Date:** 2026-07-18
**Architecture reference:** `ARCHITECTURE.md` §7.3 (supersedes ADR-0007)

> **Superseded (2026-07-23).** The seeded default admin
> (`admin@example.com` / `changeme`) is replaced by a **first-run setup wizard**
> (ADR-0017): a fresh install ships with **no** admin and is unconfigured until an
> operator creates the owner account through the wizard — no well-known
> credentials ever exist. The role-seeding half of this ADR (system roles on
> startup) still stands; only the user-seeding half is superseded. The test
> suite still seeds `admin@example.com` directly in its fixtures.

## Context

ADR-0007 bootstrapped the first Administrator by granting the role to the
first account that registered on an empty users table. Its recorded
downside was a land-grab race: on an internet-reachable fresh install,
whoever registered first owned the instance, and there was no admin at all
until someone registered. That coupling of "provision the admin" to "a
human happens to hit register first" is fragile — automated deploys,
health checks, and demos all want a known admin to exist the moment the
app is up, with nobody having registered yet.

The alternative is to *seed* the admin at install time, the same way the
system roles are already seeded (ADR-0004). The open sub-questions were
where the credentials come from and how the well-known-default-credentials
risk is handled.

## Decision

Seed a default Administrator user at startup (idempotent, in an app
`lifespan`, after the migration has created the tables + roles):

- Credentials are **hardcoded constants** (`admin@example.com` /
  `changeme`), not read from the environment.
- The seed is idempotent — created only if no user with that email exists.
- On every boot, while the admin's password still verifies against the
  default, the app logs a **loud warning** telling the operator to change
  it. A `POST /api/auth/change-password` endpoint exists so they can.
- Public registration now **never** grants above Participant — the
  first-user special case is removed entirely.

## Consequences

- Positive: a known Administrator exists the instant the app boots, with no
  registration race and no empty-admin window. Provisioning the admin is
  decoupled from human registration, matching how roles are already seeded.
- Positive: the "public registration = Participant only" invariant other
  features build on is now unconditional — there is no longer *any* code
  path where registering can elevate you.
- Negative / cost: default credentials are a well-known attack vector, and
  a hardcoded default lives in the repo. This is mitigated only by the
  startup warning and the operator's diligence — there is no forced change
  on first login (a deliberate scope choice). An install left on defaults
  is trivially compromised; the warning is the entire defense. Hardening
  (forced rotation, or making the seed a no-op unless credentials are
  explicitly provided) remains an open question in §15 and a hard blocker
  before any public/self-serve deployment.
- Forecloses: nothing structural. Because credentials are hardcoded rather
  than env-driven (a deliberate choice), making them configurable later is
  itself a small change, not a redesign.

Supersedes ADR-0007 in full.
