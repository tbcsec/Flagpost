# ADR-0016: Platform export / import — a registry-driven, additive backup

**Status:** Accepted
**Date:** 2026-07-23
**Architecture reference:** `ARCHITECTURE.md` §6 (tenancy), §9 (site settings),
§13 (data model). Related: the competition **clone** utility
(`utils/competition_clone.py`) is the config-only, in-install sibling of this.

## Context

Admins need to move a Flagpost install's data between environments (staging →
prod, a migration) and keep off-site backups. The owner asked for an
**Export/Import** pair on Admin → Site settings, with **checkboxes for what to
export** (not an implicit "everything"), and — via follow-up questions — chose
**config + live run data** (a full backup, not just setup) and **additive
"skip existing"** import semantics.

The data model is ~25 tables, most competition-scoped (§6.2), with a web of
foreign keys. Two ways to build the serialiser:

1. **Hand-code each entity** (like `competition_clone.py` does for one
   competition's config). Clear per-entity, but ~25 entities × export + import is
   a lot of duplicated plumbing, and it's easy to silently forget a table (a
   silent-data-loss footgun in a *backup* tool).
2. **A generic, registry-driven engine.** One column (de)serialiser plus a
   declared table registry (FK-remaps, import order, skip-existing keys). More
   up-front machinery, but each table is then a few lines of declaration, and
   completeness is auditable at a glance.

## Decision

**A generic engine + declared `SPECS` registry** (`utils/backup.py`).

- **Serialisation is generic**: every column of every row is dumped
  (datetimes → ISO strings, `LargeBinary` → base64, `JSON` columns pass
  through). Deferred columns (the site-settings logo blob) are `undefer`-ed on
  export so serialising them doesn't trigger a forbidden async lazy-load.
- **A single versioned JSON document** (`schema_version`), keyed by table under
  `data`, with the selected `sections`.
- **Sections are the checkboxes**: `site_settings`, `users`, `roles`,
  `competitions`, `automations`, `audit_log`. Export and import both take a
  section list; the UI offers exactly these.
- **Import is additive — "create what's missing, never modify or delete"**:
  - Top-level entities match by **natural key** and are skipped if present:
    users by display-name/email, roles by name, competitions by name, role
    assignments by (user, role, competition), automation rules by
    (name, trigger, competition, owner), audit entries by id.
  - **Competitions are atomic**: if a competition of that name exists, its whole
    owned subtree is skipped (never merged into) — no duplicate challenges.
    Cross-cutting collections (role assignments, automation rules) are additive
    per-row even against an existing competition.
  - New ids are minted on create and every FK rewritten through per-map lookups,
    so a document restores cleanly into a different install. A required FK that
    doesn't resolve skips the row; an optional one is nulled (mirrors CASCADE vs
    SET NULL). Invite codes are regenerated to avoid uniqueness clashes.
- **Full fidelity, including secrets.** A backup that couldn't restore a working
  install is a trap, so exports include password hashes, flag hashes and SMTP
  credentials. The file is therefore **sensitive** — the UI says so, and both
  endpoints are gated on `manage_site_settings` (Administrator-only, the
  permission this page already carries; no new permission for a strictly-admin
  operation).
- **Excluded tables**: `refresh_sessions` (live secrets — never), and the
  transient/derived `notifications`, `collab_documents`, `dashboard_layouts`.
  None belong in a portable backup.
- Import emits **`platform.imported`** (§3.2) for the audit log. `platform.*` is
  excluded from automation triggers (like `automation.*`) — it's an admin op,
  not a competition event.

## Alternatives considered

- **Hand-coded per-entity serialiser** — rejected for the duplication and the
  forget-a-table risk (see Context).
- **A real DB dump (`pg_dump`)** — rejected: not portable across the SQLite/
  Postgres split (ADR-0006), not section-selectable, and couldn't do the
  additive id-remapping merge into a populated install.
- **Overwrite or abort-on-conflict import** — the owner chose additive/skip;
  it's the low-risk default (can't clobber current data). Overwrite/replace can
  be added later as an explicit mode without changing the document format.
- **A dedicated `export_import_data` permission** — deferred; the operation is
  Administrator-only and lives on the site-settings page, so `manage_site_settings`
  is a faithful gate. Split it out if a narrower role ever needs export.

## Consequences

- Adding a new table to backups is a one-line `Spec` (plus its place in import
  order). Forgetting one is visible in the registry.
- The site-settings singleton is a special case: importing it **applies** the
  exported values (there's only one row to "conflict" with), rather than
  skip-existing.
- Importing competition live-data meaningfully requires importing **users** too
  (submissions/tickets/etc. reference them); unresolved user refs are skipped.
- The export file contains full credentials — operational guidance, not a code
  control, keeps it safe. A future revision could offer a redacted/"config-only"
  export toggle for sharing.
