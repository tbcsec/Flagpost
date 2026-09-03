# ADR-0038: Boot-time baseline import — provision an instance from a platform export

**Status:** Accepted
**Date:** 2026-09-03
**Architecture reference:** `ARCHITECTURE.md` §15 (first-run setup resolution,
ADR-0017), export/import backup (ADR-0016). Implements #357.

## Context

The public demo (demo.flagpost.io) resets hourly by wiping every volume and
letting `DEMO_MODE` re-seed a hardcoded sample competition and well-known
accounts (`backend/auth/demo.py`). Its baseline is *code*, not data.

Organisations want the same shape for an **internal** demo — reset on a
schedule to a baseline **they** configured (branding, competitions, users) —
without forking the backend image. ADR-0016 already gives us the right file
format (the platform export) and the authoring surface (configure in the UI,
Export backup). What was missing was a way to *apply* an export at boot, before
anyone can sign in.

The infrastructure-level answer (#356, `docs/INTERNAL_DEMO.md`) restores the
data volumes from a snapshot instead of wiping them — zero backend change,
covers SSO/SMTP secrets, but is an ops recipe. This ADR is the product-level
path: a mounted export file that a fresh instance imports on startup.

## Decision

A new setting, **`bootstrap_backup_file`** (env `BOOTSTRAP_BACKUP_FILE`,
default empty), names a mounted platform export. On startup, after role and
theme seeding and before the demo seed (`utils/bootstrap.run_bootstrap_import`,
called from the lifespan):

1. **No-op when unset.**
2. **Gated on the first-run setup state.** The import runs only when
   `instance_needs_setup()` is true (no *active* Administrator — the ADR-0017
   gate). So a normal install whose baseline carries an active owner imports
   once (the next boot sees an administrator and skips); a reset-on-a-schedule
   internal demo, whose every clean boot is unconfigured, re-imports each time.
   An already-owned instance is left untouched — a populated *additive* import
   (ADR-0016) is not a reset. (A partial baseline with **no** active owner never
   satisfies the gate, so it re-imports every boot; the import logs a warning and
   emits no `platform.imported` once its rows already exist.)
3. **Serialise across workers.** The gate is a check-then-act, and under
   `WEB_CONCURRENCY>1` (or several ADR-0031 instances against one Postgres)
   every worker's lifespan runs it — so a bare gate would let N workers import
   concurrently, racing unique constraints and duplicating keyless rows. The
   import therefore takes a transaction-scoped Postgres advisory lock and
   re-checks the gate under it; exactly one worker imports, the rest skip.
   (SQLite — the test suite and the single-worker default — is single-process
   and single-writer, so it needs none.)
4. **Fail loud.** A set-but-unreadable/invalid/wrong-version file, or any other
   import failure, raises `BootstrapError` and aborts startup rather than booting
   empty — the same refuse-to-start intent as the metrics gate (ADR-0037), though
   the mechanism differs: the metrics gate is a config-time `Settings` validator,
   while this is a runtime check on the mounted file during an unconfigured boot.
   Safe because `import_data` commits once at the end, so a failed import leaves
   the DB empty rather than half-provisioned.
5. **Mark setup complete.** `setup_completed_at` is import-*immutable* (the F2
   hardening — a crafted backup must not be able to flip the setup flag), so a
   baseline that provisioned an owner won't carry the flag across. The bootstrap
   path therefore calls `mark_setup_complete` itself after a successful import,
   the same invariant every owner-provisioning path upholds (#133). Without it
   the setup wizard would correctly refuse to run yet `SetupGuard` would still
   redirect every visitor to it.
6. **Suppress the demo seed** when a baseline file is configured: the custom
   baseline replaces the canned content, and silently injecting the well-known
   `admin`/`judge`/`participant` accounts into a company baseline would be a
   security surprise. The public `GET /api/site-settings` gains a derived
   `demo_stock_credentials` flag (`demo_mode AND not bootstrap_backup_file`);
   the login credentials card renders on it instead of `demo_mode`, so it never
   advertises accounts a baseline removed. The "resets hourly" banner still
   keys on `demo_mode` alone. (This suppresses *seeding* the stock accounts on a
   baseline boot; it does not remove stock accounts a prior `DEMO_MODE` boot
   already created — hence the "bootstrap onto a fresh volume" guidance in
   `docs/INTERNAL_DEMO.md`.)
7. Emit the existing `platform.imported` event (`user_id: null`,
   `source: "bootstrap"`) after commit, only when the import actually created
   rows — no new event type.

Because the gate is "unconfigured instance," this doubles as a general
**infrastructure-as-code bootstrap**: provision a brand-new deployment
declaratively from an export, not only a demo.

## Trust model

`import_data` runs with `actor=None`, which skips the grant-containment guard —
the bound that stops an *API* caller from importing roles/assignments carrying
permissions beyond their own. That is correct here: the file comes from the
operator's filesystem / compose config, the **same trust root** as
`JWT_SECRET_FILE`, `SECRET_ENCRYPTION_KEY_FILE` and `DATABASE_URL`. Whoever can
mount that file already owns the instance; there is no lower-privileged actor to
contain. The guard remains in force for the authenticated `POST /import` route,
which has a real actor.

## Consequences

- A platform export deliberately excludes identity providers and the SMTP
  password (per-install encryption, ADR-0020), so SSO/SMTP must be configured
  post-boot or live outside the baseline. The snapshot variant (#356) covers
  them; this path does not.
- Competition invite codes are regenerated on import (ADR-0016), so they change
  on every reset of a baseline-driven demo.
- The activity simulator only understands the stock demo seed (a shared answer
  key), so it stays off for custom baselines.
- Attachment-bearing baselines need object storage reachable at boot; the
  production compose already health-gates MinIO before the backend starts.

## Alternatives considered

- **A bespoke baseline format** (a curated YAML of "seed this"). Rejected: the
  platform export already round-trips the whole site and is the surface
  operators author in the UI; a second format would drift from it.
- **Unconditional re-import every boot.** Rejected: an additive import onto a
  populated DB is not a reset (it merges, never deletes), so it wouldn't undo
  drift — and it would fight the setup gate. The volume-snapshot path (#356) is
  the tool when a true wipe-and-restore is wanted.
- **Import via the authenticated route from an init container.** Rejected:
  needs a bootstrapped admin token to exist first — the chicken-and-egg the
  setup gate exists to avoid — and re-implements at the ops layer what a
  startup hook does in one place.
