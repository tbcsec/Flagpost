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
**Tier 0 (Foundation) — not yet started.** See `docs/ROADMAP.md` for the
full tier breakdown. Don't build Tier 2+ features before the current
tier's items exist and work — a Tier 1 PR that also sneaks in Tier 3
polish is scope creep, not helpfulness.

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
# Backend
cd backend && uvicorn main:app --reload
docker compose run --rm backend alembic upgrade head

# Frontend
cd frontend && npm run dev
```

<!-- These are the intended commands per ARCHITECTURE.md §2/§14, not yet
verified against a working docker-compose.yml. Confirm and update once
the Tier 0 scaffold exists. -->

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

Not yet established — this is a Tier 0 task, not a settled fact. If
you're the one setting it up, propose pytest (backend) and Vitest
(frontend), and record the decision as an ADR rather than picking it
silently mid-PR.

## Keeping this file honest

If you catch yourself re-explaining the same thing twice in a session, or
a rule here turns out to be wrong, fix it here. If it's a real
architectural decision (not just a typo), update `docs/ARCHITECTURE.md`
and/or add an ADR too — don't let this file and the real docs drift apart.