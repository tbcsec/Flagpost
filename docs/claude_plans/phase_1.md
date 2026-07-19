# Tier 1 — Minimum Viable Competition: Phased Plan

## Context

Tier 0 (Foundation) is complete and tagged (`tier-0`): event bus, JWT/RBAC,
the Competition tenancy root, the design-token layer, and the frontend hook
layer. Tier 1 (`docs/ROADMAP.md` items 6–15) turns that foundation into a
platform that can run **one real competition end to end** — teams, challenges,
files, submission, scoring, a live scoreboard, announcements, and hints.

This plan also folds in a change you asked for that isn't a Tier 1 feature:
**replace the "first registered user becomes admin" bootstrap (ADR-0007) with
a seeded admin user that has default credentials.** That's Phase 0 — done
first because it touches auth, which everything else depends on.

Governing docs: `ARCHITECTURE.md` §4 (real-time), §11 (module system), §13
(domain model + submission/storage), §7 (RBAC — the permission catalog already
contains every key Tier 1 needs), and ADR-0009 (event dispatch is synchronous
for now — fine through Tier 1, since every handler stays in-process/fast).

Conventions held throughout (from CLAUDE.md / ARCHITECTURE §1): every mutation
emits a past-tense `<entity>.<verb>` event already in §3.2 (add new ones there
first); every tenant-scoped table uses `CompetitionScopedMixin` and every query
filters by `competition_id` (§6.2); permission checks go through
`require_permission` (§7.6); one router + one hook module per domain; colours/
spacing from tokens (§9). One migration and a green pytest+vitest run per phase;
one commit per phase.

**Decisions you set for Phase 0:** hardcoded default admin credentials (not
env-configurable); seed as-is with a loud startup warning while the password is
still the default (no forced-change gate).

---

## Phase 0 — Seeded admin user (supersedes ADR-0007)

Replace the first-user-admin bootstrap with an install-time seeded Administrator.

- `auth/seed.py`: add `DEFAULT_ADMIN_EMAIL = "admin@ctf.local"`,
  `DEFAULT_ADMIN_PASSWORD = "changeme"`, `DEFAULT_ADMIN_DISPLAY_NAME`, and
  `seed_admin_user(session)` — idempotent: if no user with the default email
  exists, create it (`hash_password`) + a global Administrator `RoleAssignment`.
- `main.py`: add a FastAPI `lifespan` that on startup seeds the admin and, if
  the admin's password still `verify_password`s against the default, logs a
  prominent warning ("default admin credentials in use — change them"). (Roles
  keep coming from the migration; the admin is seeded at startup because
  hashing a password inside a migration is awkward and the app always boots
  after `alembic upgrade`.)
- `routers/auth.py`: **remove** the first-user bootstrap block (the
  `is_first_user` logic, lines ~77–112). Registration now always creates a
  plain user with no role assignment (Participant access comes from joining a
  competition, §7.5).
- **Change-password endpoint** (small, needed to make the warning actionable):
  `POST /api/auth/change-password` (authenticated; `current_password`,
  `new_password`) → verify current, set new hash, revoke the user's other
  refresh sessions. New schema in `schemas/auth.py`. *(Flag for review: this is
  a minor addition beyond the literal ask, but without it the default password
  can never be rotated.)*
- Tests: replace `test_first_user_is_admin_*`; add seeded-admin-can-log-in +
  has `create_competition`, and change-password happy/negative paths. Update
  `tests/conftest.py` fixture to call `seed_admin_user` after `seed_system_roles`,
  and update `test_competitions.py` to log in as the seeded admin instead of
  relying on first-user-admin.
- Docs: **ADR-0010** (seeded admin w/ default creds + startup warning),
  mark ADR-0007 `Superseded by ADR-0010`, update the ADR index; refresh the
  §15 admin-bootstrap open question (risk shifts from land-grab to default
  creds); fix the register-page copy ("first account becomes administrator" is
  no longer true) and update CLAUDE.md's auth summary.
- No new columns → **no migration** this phase.

## Phase 1 — Module loader (§11.1, kernel — first Tier 1 item per CLAUDE.md)

A real-but-minimal backend module registry; Challenges (Phase 4) is its first
consumer, so it's built now rather than speculatively.

- `backend/modules/` (loader) — discover in-box modules, each exposing a
  manifest (id, provides.router, event_listeners, dependencies, and a
  `required_core: bool`). A `setup(app, event_bus, db_factory)` entry point per
  module (§11.1). Loader mounts routers, refuses a module whose declared
  dependency isn't active, and tracks enabled state — required-core modules are
  always enabled and carry no admin toggle (§11.3, ADR-0002).
- Refactor the existing `competitions` router to register through the loader as
  the first required-core module, proving the path end to end.
- **Scope cut (note for review):** frontend extension slots / `PluginSlot`
  (§11.2), plugin settings, widgets, and the enable/disable *admin UI* are
  deferred — no optional module ships in Tier 1, so core pages render core
  components directly. The manifest carries the fields so they're not a
  retrofit later.
- Tests: loader discovers/mounts a module, enforces a missing dependency, and
  required-core is always-on.

## Phase 2 — Competition management, admin (#6)

Finish what Tier 0 deferred: editing a competition.

- Extend `Competition`: `registration_opens_at` / `registration_closes_at`,
  `visibility` (`public` | `private`). `PATCH /api/competitions/{id}` gated on
  `edit_competition` (competition-scoped — exercises the path-param resolution
  in `require_permission`), emitting **`competition.updated`** (add to §3.2
  first). Migration adds the columns.
- Frontend: replace the Tier 0 create *dialog* with a fuller create/edit form +
  a competition settings page; extend `use-competitions.ts` with an update
  mutation.

## Phase 3 — Team management (#7)

- Models: `Team` (competition-scoped) + `TeamMembership` (team ↔ user), honoring
  the competition's `participation_mode`. Endpoints: create, invite/join (invite
  code), leave; events `team.created`, `team.member_joined` (both already in
  §3.2). `team_*` permissions from §7.1 for staff views.
- Frontend: `use-teams.ts` + team create/join/leave/view UI. Enforce
  team-vs-individual mode from the competition setting.

## Phase 4 — Challenges + categories, admin (#8, #9)

- Register **Challenges as the first required-core module** through Phase 1.
- `Category` (competition-scoped) and `Challenge` (competition-scoped): title,
  `description` rich text via **TipTap** (stored as JSON), `category_id`,
  `points`, `visibility` (draft/published), and flag config: `flag_type`
  (`static` | `regex`), `case_insensitive`, with the static flag stored
  **hashed** and **never returned** in any response, including admin views
  (§13.2). Events `challenge.created`, `challenge.published`. Migration for both
  tables.
- Frontend: admin challenge editor (TipTap) + category management; `use-challenges.ts`,
  `use-categories.ts`. Admin edit screen shows *that* a flag is set, not its value.
- (File attachments deferred to Phase 5.)

## Phase 5 — File / asset storage, MinIO (#10)

- Object-storage client behind a small interface (so tests use an in-memory fake
  and keep ADR-0006's no-infra suite). Upload endpoint writing keys
  `<competition_id>/<challenge_id>/<filename>` (§13.3); download via **short-lived
  signed URLs** issued only after a `challenge_view` check (§13.3) — no public
  bucket paths. Wire attachments onto challenges.
- Frontend: file upload in the challenge editor; download through signed URLs.

## Phase 6 — Challenge browsing & submission + scoring (#11, #12)

- Competitor `GET` challenge list/detail (published + scoped only). `Submission`
  model (competition-scoped, via challenge). Flag submission endpoint (§13.2):
  **server-side comparison only**, **per-user/per-team rate limit** (sliding
  window behind a limiter interface — Redis impl in prod, in-memory in tests),
  **idempotent on repeat-correct** (first correct is authoritative, no re-award
  / no re-emit), **every attempt logged** (not just successes). Emits
  `challenge.solved` with `is_first_blood`. Scoring: static points on first
  correct, duplicate handling.
- Frontend: competitor challenge browse + detail + submission UI with solve state.

## Phase 7 — Real-time layer + live scoreboard (#13)

- First WebSocket subsystem (§4.1): a connection manager, `wss://…/ws/<type>/<id>`
  rooms, **first-frame JWT auth handshake** (token in the first message, bounded
  by a short server timeout — never in the URL, ADR-0003), reusing the same
  access token as REST. Scoreboard computation (ranks teams or individuals per
  `participation_mode`); a `challenge.solved` event-bus handler broadcasts
  updates to the competition's scoreboard room. Presence/soft-lock (§4.1) is
  **Tier 2 (#19)** — not built here.
- Frontend: scoreboard page with live updates + exponential-backoff reconnect.
- Note: in-process WS manager is fine for the single-instance compose
  deployment; multi-instance fan-out (Redis pub/sub) stays deferred per ADR-0005.

## Phase 8 — Announcements (#14)

- `Announcement` (competition-scoped); admin create gated on
  `announcement_create`, emits `announcement.published`; live push over the
  Phase 7 WS layer to the competition's announcement room.
- Frontend: announcements admin + a live banner.

## Phase 9 — Basic hints (#15)

- `Hint` attached to a challenge; reveal-on-request endpoint with optional point
  cost, emitting `challenge.hint_requested`; scoring integration for the cost.
  (No automation-driven release — that's a deferred automation action, §5.3.)
- Frontend: hint reveal UI on the challenge detail screen.

---

## Cross-cutting notes

- **Events:** only `competition.updated` is new to §3.2 (Phase 2); every other
  Tier 1 event already exists in the vocabulary.
- **ADR-0009 (sync dispatch)** holds through Tier 1 — the scoreboard/announcement
  broadcasts are in-process and fast. Keep WS-broadcast handlers non-blocking;
  the first genuinely slow handler (automation webhook) is Tier 2+ and is the
  trigger to revisit ADR-0009.
- **New infra first-use:** TipTap (Phase 4), MinIO (Phase 5), Redis (Phase 6
  rate limiting), WebSockets (Phase 7). Object store and rate limiter sit behind
  interfaces so the pytest suite stays infra-free (ADR-0006).
- **RBAC:** every permission Tier 1 needs already exists in §7.1 — no catalog
  additions expected; the custom-role editor UI stays Tier 2 (#21).

## Verification (per phase + at the end)

1. `cd backend && .venv/bin/pytest` and `cd frontend && npm run test` green.
2. `docker compose up --build` migrates cleanly; native dev servers (Node 20)
   still start.
3. End-to-end smoke on the running stack: log in as the seeded admin → create a
   competition → add a team/challenge/category/file → submit a flag as a
   competitor → watch the scoreboard update live → post an announcement → reveal
   a hint. Confirm the matching events land in `audit_log`.

## Out of scope (Tier 2+, per ROADMAP)

Judge/admin dashboard, challenge review workflow, support tickets, presence
indicators, per-competition theming, custom-role editor, automation engine, AI,
plugin marketplace / extension-slot UI, dynamic/decay scoring, CRDT co-editing.
