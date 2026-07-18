# CLAUDE.md

## What this project is

A modern, open-source CTF competition management platform. Product
rationale lives in `docs/VISION.md`. Technical design lives in
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

<!-- Update this line as tiers complete. -->
**Tier 0 (Foundation) — complete (tagged `tier-0`). Tier 1 (Minimum
Viable Competition) is the active tier.** See `docs/ROADMAP.md` for the
full tier breakdown. Don't build Tier 2+ features before the current
tier's items exist and work — a Tier 1 PR that also sneaks in Tier 3
polish is scope creep, not helpfulness.

What Tier 0 landed: the async event bus (§3) with an audit-log consumer,
JWT auth + roles/permissions-as-data (§7), the Competition tenancy root
(§6) with a create path, the Tailwind v4 `@theme` token layer + shadcn
primitives (§9), and the TanStack Query hook layer + Zustand auth store
(§8). Decisions made while building it are recorded in ADR-0008 (stateful
refresh sessions) and ADR-0009 (synchronous event dispatch for now) —
read those before changing auth or the event bus. The admin is a **seeded
default account** (`admin@example.com` / `changeme`, ADR-0010, which
superseded the first-user bootstrap of ADR-0007); public registration
never grants above Participant, and a loud startup warning fires while the
default password is unchanged.

First up in Tier 1: the **module loader** (§11.1). It's kernel per
ADR-0002 but was deferred out of Tier 0 on purpose — its first real
consumer is Challenges, so it's built now, alongside them, rather than
speculatively.

## Non-negotiable architectural rules

From `docs/ARCHITECTURE.md` §1, enforced by convention and code review,
not the compiler — treat these as hard rules, not defaults to reconsider
per-feature:

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
  (§8). Components never call the API client directly.
- **Colors and spacing come from design tokens**, never a raw hex value
  or magic number in a component (§9). Missing a token is a reason to add
  the token, not to inline the hex.
- **New backend features register through the module loader** (§11.1),
  including required-core ones — check §11.3 for which tier a feature
  belongs to before deciding whether it needs an admin-facing toggle.

## Don't build yet

Explicitly deferred past MVP (`docs/ROADMAP.md`, "Explicitly Deferred"
section). If a task seems to need one of these, flag it and ask rather
than quietly building a scoped-down version:

- Full automation engine (webhook actions, conditions/actions UI,
  personal rules) — the event bus exists from Tier 0; the engine
  consuming it doesn't yet.
- AI integration — administrator or competitor assistant.
- SSO / LDAP / SAML — password auth only until after public launch
  (`docs/adr/0003-jwt-access-refresh-auth.md`).
- Plugin marketplace / third-party modules — the module *mechanism* is
  used for required-core features starting in Tier 0, but the
  marketplace path stays closed.
- Multi-competition tenancy *consolidation views* — `competition_id`
  scoping is required from Tier 0; cross-site rollups are not.
- Dashboard drag-and-drop — ships as a fixed layout first (Tier 2), the
  customizable layer comes later.
- Collaborative rich-text (Y.js/CRDT) editing — presence-only in Tier 2;
  true co-editing is a later lift.

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