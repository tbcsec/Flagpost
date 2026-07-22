# CLAUDE.md

## What this project is

Flagpost — a modern, open-source CTF competition management platform.
Product rationale lives in `docs/VISION.md`. Technical design lives in
`docs/ARCHITECTURE.md` and is binding, not aspirational — if code and
`ARCHITECTURE.md` disagree, that's a bug in one of them, not a judgment
call to make silently.

## Read these before you start — don't duplicate them here

- `docs/VISION.md` — what and why.
- `docs/ARCHITECTURE.md` — how. 15 sections; check the relevant one
  before designing anything new (event bus, RBAC, tenancy, automation,
  and the module system each have a section — don't reinvent a pattern
  that's already specified).
- `docs/ROADMAP.md` — build order, in tiers. Check which tier is current
  before starting new work.
- `docs/adr/` — why past decisions were made the way they were. Check
  before proposing an alternative to something already decided. If an
  ADR's decision looks wrong given what you're building, say so and
  propose a new ADR — don't quietly work around it.

If something in this file conflicts with those three, they win. Fix this
file, don't ignore it.

## Current build stage

<!-- Update this line as tiers/phases complete. -->
**Tier 0, Tier 1, and Tier 2 ("Makes It Good") are all complete — Tier 2 was
built phase-by-phase per `docs/claude_plans/phase_2.md` (Phases 0–5 all
shipped). Tier 3 is the current tier and is now scoped/planned in
`docs/claude_plans/phase_3.md` (Phases 0–9, nothing started yet). An owner
revision pulled three previously-deferred subsystems up into Tier 3 — the
**full automation engine** (§5), **dashboard drag-and-drop** (§10), and
**collaborative rich-text/CRDT editing** (§4.2) — alongside the polish items
(feedback/survey, analytics, onboarding, a11y). Build order is **automation
engine first** (full spec), then the rest; work the phases in order and don't
start a phase without confirming scope.** See `docs/ROADMAP.md` for the tier
breakdown and `phase_3.md` for the phase-by-phase plan.

What's built:

- **Tier 0** — the async event bus (§3) with an audit-log consumer, JWT
  auth + roles/permissions-as-data (§7), the Competition tenancy root (§6),
  the Tailwind v4 `@theme` token layer + shadcn primitives (§9), and the
  TanStack Query hook + Zustand store layer (§8).
- **Tier 1** — the manifest-driven module loader (§11.1); competition
  admin (edit/schedule/visibility); teams; challenges + categories; MinIO
  file attachments; flag submission + static-points scoring; the WebSocket
  layer (§4.1) with a live scoreboard; announcements; and hints. The full
  authenticated app shell (sidebar + topbar) from the design handoff is
  wired — see `docs/UI-INTEGRATION-NOTES.md` for what's real vs. still
  placeholder.
- **Tier 2 Phase 0** (pre-Tier-2 gap fixes) — competition join (public
  self-serve + invite code; the only way into an individual-mode
  competition), enforced competition visibility, role-aware navigation via
  `GET /api/auth/me/permissions`, tz-aware timestamps, an admin
  **audit-log / event viewer** (its own required-core module) with
  GitLab-style filtering, and UI polish (toasts, skeletons, scoreboard
  medals, solve celebration, persisted theme, responsive drawer).
  `change-password` now emits `user.password_changed`.
- **Tier 2 Phase 1** — the judge/admin **operational dashboard** (§10) on a
  widget-registration architecture: a registry of self-contained,
  size-declaring widgets (`lib/dashboard/registry.tsx`) rendered in a fixed
  per-role layout, so the (deferred) drag-and-drop layer is additive later,
  not a rewrite. Backend stats/recent-solves/challenge-health/me endpoints
  in a required-core `dashboard` module.
- **Tier 2 Phase 2** — **support tickets** (§4.4), a required-core `tickets`
  module: competitor create/reply, staff assign/resolve/internal notes,
  ownership-scoped reads, a live per-ticket WS thread + a staff support
  queue room, and the one sanctioned **audio cue** for new tickets/replies.
  Registers a support-queue dashboard widget into Phase 1's registry.
- **Tier 2 Phase 3** — **presence** (§4.1) on the WS layer: a room type opts
  in with a `presence_member` builder and the connection manager tracks a
  per-user, tab-deduped "who's here" set, broadcasting it on change with a
  debounced clear (`ws_presence_grace_seconds`) so brief reconnects don't
  flicker. WS-level state only — no event, REST, or migration. Drives "N
  others viewing" on the challenge dialog (a new presence-only `challenge`
  room) and "a judge is looking at this ticket" on the Phase 2 ticket room.
  Frontend: `usePresence` + `PresenceIndicator`.
- **Tier 2 Phase 4** — **site-wide theming** (§9), a required-core
  `site_settings` module: a **SiteSettings singleton** (platform name +
  default palette + accent), public `GET` (login/register brand before auth) +
  `manage_site_settings`-gated `PUT` emitting `site.settings_updated`.
  Curated palette presets (**Harbor/Eclipse/Umbra** dark, **Daybreak/Sandstone**
  light — a palette is a full token set, not a free-form background picker);
  accent is one hue overriding only `--primary`/`--ring` (+ YIQ-chosen
  foreground), preset or custom hex, never touching `--success`/the logo
  (LOGO-SPEC §7). `lib/theme.ts` (registry + colour math) + a `ThemeApplier`
  (palette = per-user override ?? site default; no-flash inline script) + the
  topbar palette menu + the wired Admin → Appearance page. System roles now
  **re-sync from the permission catalog on every startup** (`seed_system_roles`)
  so a newly-added permission reaches an already-migrated Administrator.
- **Tier 2 Phase 5** — **custom role editor** (§7.4), a required-core `roles`
  module gated on `manage_roles`: list roles + the categorized permission
  **catalog**, create/clone/edit/delete **custom** roles, and
  list/assign(by-email)/unassign assignments. Invariants: system roles are
  read-only (clone to vary), assignment scope matches the role, no deleting an
  assigned role, no unassigning the last Administrator. Emits
  `role.created`/`updated`/`deleted`/`assigned`/`unassigned`. Frontend: the
  wired Admin → Roles page (matrix editable for custom / read-only for system;
  competition roles hide global permissions) + `use-roles.ts`. No migration —
  the role/assignment tables are Tier-0.

Read before touching the relevant area: ADR-0008 (stateful refresh
sessions), ADR-0009 (synchronous event dispatch), ADR-0010 (seeded default
admin creds), ADR-0011 (site-wide theming only — per-competition deferred).
The admin is a **seeded default account** (`admin@example.com` / `changeme`,
ADR-0010, superseding the first-user bootstrap of ADR-0007); public
registration never grants above Participant, and a loud startup warning
fires while the default password is unchanged.

**Tier 2 scope notes** (owner decisions, reflected in the plan): the
challenge lifecycle (ROADMAP #17) is **deferred to a future tier**, and
theming is **site-wide only** for now (ROADMAP #20 rescoped from
per-competition; ADR-0011).

**Local dev note:** `.claude/launch.json`'s backend config runs against
SQLite by default (`DATABASE_URL` env var overrides it) so `preview` needs
no infra, matching the test stack (ADR-0006). Migrations run automatically
on every start. Use `docker compose up` for the full Postgres/Redis/MinIO
stack.

## Non-negotiable architectural rules

From `docs/ARCHITECTURE.md` §1, enforced by convention and code review
(and, where marked below, by ESLint — `frontend/eslint.config.mjs`) — treat
these as hard rules, not defaults to reconsider per-feature:

- **Every mutation emits an event** through the event bus (§3), using the
  `<entity>.<verb>` past-tense vocabulary already defined in §3.2. Don't
  invent a new event type without adding it there first.
- **Every query and route is scoped by `competition_id`** at the
  data-access layer, never left to an individual endpoint to remember
  (§6.2). Writing a query against a tenant-scoped table with no
  `competition_id` filter is a bug, not a shortcut.
- **Permission checks go through `require_permission`**, never an inline
  role check (§7.6). If the permission you need doesn't exist yet, add it
  to the categorized list in §7.1 first.
- **One hook module per frontend domain** under `frontend/src/lib/hooks/`
  (§8). Components never call the API client directly. *(ESLint: no
  `@/lib/api` import outside `lib/hooks/`.)*
- **Colors and spacing come from design tokens**, never a raw hex value
  or magic number in a component (§9). Missing a token is a reason to add
  the token, not to inline the hex. *(ESLint: no raw hex literals in
  `app/`/`components/`, brand mark excepted.)*
- **New backend features register through the module loader** (§11.1),
  including required-core ones — check §11.3 for which tier a feature
  belongs to before deciding whether it needs an admin-facing toggle.

## Don't build yet

Explicitly deferred past MVP (`docs/ROADMAP.md`, "Explicitly Deferred"
section). If a task seems to need one of these, flag it and ask rather
than quietly building a scoped-down version:

- AI integration — administrator or competitor assistant.
- SSO / LDAP / SAML — password auth only until after public launch
  (`docs/adr/0003-jwt-access-refresh-auth.md`).
- Plugin marketplace / third-party modules — the module *mechanism* is
  used for required-core features starting in Tier 0, but the
  marketplace path (listing/discovery + untrusted-code sandboxing) stays
  closed.
- Multi-competition tenancy *consolidation views* — `competition_id`
  scoping is required from Tier 0; cross-site rollups are not.
- Per-competition / white-label theming — site-wide only for now
  (ADR-0011); the per-competition variant may return later.

Note: the **automation engine**, **dashboard drag-and-drop**, and
**collaborative rich-text/CRDT editing** were on this list but an owner
revision moved them into **Tier 3** (see `phase_3.md`). Build them in
phase order, not ad hoc — the plan is what to follow.

## Stack

Fixed by `docs/ARCHITECTURE.md` §2 — don't substitute an alternative to
something already decided there (e.g. Zustand + TanStack Query, not
Redux; SQLAlchemy 2.x async, not a different ORM).

```
# Whole stack (Postgres/Redis/MinIO + backend + frontend), verified.
# The backend container runs `alembic upgrade head` before serving, so the
# DB is migrated + system roles seeded automatically on first boot.
docker compose up --build     # frontend :3000, backend :8000

# Backend only (needs a venv — this host's Python is externally-managed)
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head          # against a reachable Postgres
.venv/bin/uvicorn main:app --reload

# Frontend only — REQUIRES Node 20+ (Tailwind v4's engine, @tailwindcss/oxide).
cd frontend && npm install && npm run dev
```

<!-- Verified end-to-end on 2026-07-18: docker compose up migrates + seeds,
register->admin bootstrap, RBAC-gated competition create (participant 403),
and competition.created/user.registered land in audit_log. Local Node here
is 18, which can't run the frontend (Tailwind v4 needs Node 20); the Docker
frontend image is node:20-alpine, so `docker compose up` is the reliable
path on this machine. -->

## Code conventions

- Backend: Pydantic schemas (`backend/schemas/`) are separate from
  SQLAlchemy models (`backend/models/`) — never return a model directly
  from a route.
- Backend: one FastAPI router per domain (`backend/routers/`), mirroring
  the one-hook-per-domain convention on the frontend.
- Frontend: server state through TanStack Query hooks only; Zustand is
  for client/UI state (auth, active competition, prefs) — don't put
  server data in a Zustand store.
- Migrations: `YYYY-MM-DD_<revid>_<desc>.py`, one migration per PR. Never
  hand-edit a migration that's already been applied anywhere.

## Testing

Established in Tier 0 (see `docs/adr/0006-testing-stack.md`):

- **Backend:** pytest + pytest-asyncio, httpx ASGI transport, SQLite
  (aiosqlite) so no infra is needed. `cd backend && .venv/bin/pytest`.
  The suite builds the schema from `Base.metadata` and seeds roles from
  `auth/seed.py` (the same specs the migration uses).
- **Frontend:** Vitest + Testing Library + jsdom.
  `cd frontend && npm run test`.

Keep SQLite/Postgres differences in mind (models stay portable, generic
`JSON`, `render_as_batch` migrations) — the ADR spells out the tradeoff.

## Keeping this file honest

If you catch yourself re-explaining the same thing twice in a session, or
a rule here turns out to be wrong, fix it here. If it's a real
architectural decision (not just a typo), update `docs/ARCHITECTURE.md`
and/or add an ADR too — don't let this file and the real docs drift apart.