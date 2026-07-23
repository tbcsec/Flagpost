# ADR-0017: First-run setup wizard (no seeded default admin)

**Status:** Accepted
**Date:** 2026-07-23
**Architecture reference:** `ARCHITECTURE.md` §7 (Users & Roles), §7.3
(bootstrap), §9 (site settings)
**Supersedes:** the user-seeding half of [ADR-0010](0010-seeded-admin-default-credentials.md)
(seeded default admin). Builds on ADR-0015 (username-primary identity).

## Context

ADR-0010 seeds an administrator with well-known credentials
(`admin@example.com` / `changeme`) on every startup, guarded by a loud
"change the default password" warning. It's simple, but **shipping known
credentials is a security smell**: an operator who forgets the warning leaves an
admin account with a public password, and the very-first-login story is "log in
as a hard-coded user, then immediately change everything."

The owner asked for a **first-run setup wizard**: a fresh instance should force
initial configuration — create the owner account (so no hard-coded creds) and set
branding + a few site-wide settings (nothing competition-scoped).

## Decision

**A fresh install ships with no administrator and is "unconfigured" until an
operator completes a one-time public wizard.**

- **First-run signal**: `auth.setup.instance_needs_setup(db)` — true until an
  **active user holds the global Administrator role**. No new column or migration:
  it's derived from the existing role model, so it self-corrects and needs no
  bookkeeping flag. (System roles are still seeded on startup so the wizard has an
  Administrator role to assign.)
- **The wizard endpoints** (`plugins/setup`, required-core, public):
  `GET /api/setup/status` → `{needs_setup}`, and `POST /api/setup` which — only
  while `needs_setup` — creates the owner (with a global Administrator
  assignment), applies the initial site settings (platform name, palette, accent,
  registration policy), and issues a session so the operator lands signed in.
  Once an admin exists it **409s**, so it can't mint a second owner or reset an
  install.
- **Guards while unconfigured**: public registration is refused
  (no self-serve accounts before an owner exists), and login simply has no users.
- **Startup no longer seeds an admin** (`main.py` lifespan drops
  `seed_admin_user` + the default-password warning; keeps `seed_system_roles`).
- **Frontend**: a `SetupGuard` mounted above every page redirects to `/setup`
  while `needs_setup`, and away once done; `/setup` is a 3-step wizard (account →
  branding → options) with live theme preview.
- **Scope of the wizard**: the owner account, platform name + palette + accent,
  and the registration policy. The **logo and SMTP** are deliberately left to
  their dedicated Admin pages (Appearance / Site settings) — the wizard stays
  short, and both are already fully wired there. Nothing competition-scoped.

## Alternatives considered

- **Keep the seeded default admin** (ADR-0010) — rejected per the owner ask; the
  known-credentials smell is the whole thing being removed.
- **A `setup_completed` flag on site settings** (+ migration) — rejected as
  redundant: "an active admin exists" is a faithful, self-correcting signal that
  needs no new state. (Downside: deleting the last admin reverts to setup mode —
  but the last-admin guard already prevents that, and reverting is a reasonable
  recovery path.)
- **CLI/env-var admin provisioning** — a fine complement, but it doesn't give the
  guided branding step the owner wanted, and it's less discoverable than a wizard.
  Could be added later for headless installs without changing this contract.

## Consequences

- No credentials ship with Flagpost; the first thing an operator sees on a fresh
  install is the wizard.
- The **test suite** still seeds `admin@example.com` directly in its fixtures
  (conftest), so existing tests are unaffected; `test_setup.py` removes that admin
  to exercise the unconfigured path.
- Dev/preview: a fresh `dev.db` is unconfigured — the operator runs the wizard
  once (it persists), rather than logging in with a default account.
- The wizard is intentionally minimal; richer first-run steps (sample
  competition, invite teammates) can be added as steps without changing the
  provisioning contract.
