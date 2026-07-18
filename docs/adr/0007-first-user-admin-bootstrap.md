# ADR-0007: First registered user becomes the Administrator

**Status:** Superseded by [ADR-0010](0010-seeded-admin-default-credentials.md)
**Date:** 2026-07-18
**Architecture reference:** `ARCHITECTURE.md` §7.3, §7.5

> **Superseded (2026-07-18):** the first-user bootstrap was replaced by a
> seeded default administrator before it ever shipped in a release — see
> ADR-0010 for why (the land-grab race and empty-admin window this ADR
> flagged as costs turned out not to be worth carrying). Kept for history.

## Context

Public registration only ever grants the Participant role (§7.3) — the
platform must not let anyone self-assign elevated access. But a fresh
install has no users at all, so the *first* Administrator has to come from
somewhere before anyone can manage roles, create competitions, or do
anything else that needs a global permission. Nothing bootstraps that
account yet, and RBAC is meaningless until one exists.

Three real options were on the table:

1. **Env-var bootstrap** — on startup, if no admin exists and
   `ADMIN_EMAIL`/`ADMIN_PASSWORD` are set, create it. Deterministic and
   avoids any race, but adds config and a second account-creation path.
2. **First registered user is admin** — the first account created on an
   empty users table is granted the global Administrator role.
   Zero-config, but on an internet-reachable fresh install whoever
   registers first owns the instance.
3. **Setup CLI command** — a manual `create_admin` script. Explicit and
   safe, but an extra manual step in every deployment and awkward in
   Docker.

## Decision

Option 2: the first account registered while the `users` table is empty
is granted a global (`competition_id = NULL`) Administrator
`RoleAssignment`. The registration path guards this on the empty-users
check so it can never re-trigger, and logs a prominent warning when it
fires. All later registrations are Participants.

## Consequences

- Positive: zero-config, Docker-friendly bootstrap — `docker compose up`
  then register, and you have a working admin with no extra env or manual
  step.
- Positive: the elevation is confined to exactly one code path, guarded by
  a single invariant (empty users table), so it's easy to audit that
  nothing else grants above Participant.
- Negative / cost: on an internet-reachable install that sits with an
  empty users table, whoever registers first becomes admin — a
  land-grab race. Acceptable for the local/self-hosted-by-the-operator
  model Tier 0 targets (you register immediately after standing it up),
  but **not** safe for a public or multi-tenant self-serve deployment
  as-is. Hardening (env-var-seeded admin, a one-time setup token, or
  locking registration until an admin exists) is tracked as an open
  question in §15 and should land before any public/self-serve launch.
- Forecloses: nothing. The hardening options above layer on top of this
  without changing the "public registration = Participant only" rule,
  which is the part other features actually depend on.
