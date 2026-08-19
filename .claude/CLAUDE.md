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
- `docs/ROADMAP.md` — the pre-1.0 tier breakdown (history) and the
  post-1.0 release milestones (live). Check what's in the current
  milestone before starting new work; GitHub is the source of truth.
- `docs/adr/` — why past decisions were made the way they were. Check
  before proposing an alternative to something already decided. If an
  ADR's decision looks wrong given what you're building, say so and
  propose a new ADR — don't quietly work around it.

If something in this file conflicts with those three, they win. Fix this
file, don't ignore it.

## Where the project is

Tiers 0–3 are complete and the platform shipped **v1.0.0 on 2026-07-25**, then
v1.1.0, v1.1.1, v1.2.0, v1.3.0 and **v1.4.0 (2026-08-13)**. **The latest tag is
`v1.4.0`; `main` is now `1.4.0-src`**, accumulating the not-yet-tagged v1.5.0
milestone (`SOURCE_BUILD_VERSION` in `backend/config.py`, bumped at tag time;
see CONTRIBUTING → "Cutting a release").

The tier/phase plans in `docs/claude_plans/` are **finished and historical** —
don't work "the next phase". Work is tracked as **GitHub issues against version
milestones** (`gh issue list --milestone v1.5.0`); `docs/ROADMAP.md` →
"Post-1.0 releases" summarises them.

Two things follow from that. First, this is **released software with real
deployments** — a migration that corrupts data or a change that breaks upgrade
is a different class of mistake than it was pre-1.0. Second, the detailed
history of how each subsystem got built is in **git log, the ADRs, and
`docs/claude_plans/`**, not here; this file is orientation, not a changelog.

## What exists — a map

The point of this section is so you don't build something twice or miss a
mechanism that already solves your problem. It names *where* things live; the
authority on *how* they work is `docs/ARCHITECTURE.md` and the code.

**Backend** is a small kernel (auth/RBAC, the Competition tenancy root, the
event bus, the module loader) plus **22 modules** in `backend/plugins/`, each a
`plugin.yaml` manifest + a `setup()` that mounts routers and subscribes
listeners (§11.1). Exactly **six are optional** — per-competition toggleable
via `competition_modules`: **`automations`**, **`feedback`**, **`analytics`**,
**`certificates`**, **`reports`**, and **`ai`** (this last one additionally ships *inert*
behind a site master switch — see the AI bullet below). The other sixteen are
required-core and always on:
`announcements`, `audit_log`,
`challenges`, `collab`, `competitions`, `dashboard`, `hints`, `notifications`,
`roles`, `scoring`, `setup`, `site_settings`, `sso`, `teams`, `tickets`,
`users`.

Subsystem by subsystem, with the non-obvious bits called out:

- **Auth & identity** — JWT access + rotating stateful refresh sessions
  (ADR-0003, ADR-0008). Identity is **username-primary with optional email**
  (ADR-0015): the display name is the case-insensitively-unique login handle,
  and login accepts name *or* email via `auth/identity.find_by_identifier`.
  **External auth is OIDC + OAuth2 + SAML + LDAP** (`sso` module,
  ADR-0021/0022): one `IdentityProvider` framework — sub-first linking,
  posture-aware trust (`open`/`closed`), JIT provisioning as Participant, local
  login surviving as break-glass because a JIT user gets an undisclosed random
  password hash. Two kinds break the OIDC-shaped mould: **LDAP** is not a
  redirect (a bind inside `POST /api/auth/login`, tried only after local verify
  fails), and **`oauth2`** (ADR-0033) has no ID token — identity comes from a
  server-side userinfo call plus a configured claim map, which is what makes
  GitHub/Discord presets rather than integrations. Also: self-service password
  reset, email verification (admin-toggleable), self-service email change, a
  registration domain allowlist, and personal **API tokens** (`flp_`-prefixed,
  minting is self-only by route shape).
- **RBAC** — permissions as data (ADR-0004), 43 of them in
  `auth/permissions.py`, each with a category and a `global`/`competition`
  scope. System roles **re-sync from the catalog on every startup**
  (`seed_system_roles`), so a new permission reaches an already-migrated
  Administrator without a migration.
- **Events** — `utils/event_bus`, 76 event types in `utils/event_catalog.py`.
  `emit()` awaits foreground handlers (audit + WS broadcasts) and schedules
  `background=True` ones fire-and-forget (ADR-0012) — that's the lane
  webhooks/email use.
- **Real-time** — one WS layer (§4.1) serving scoreboard, announcements,
  tickets, per-user rooms, presence, a per-competition `activity` room (id-only
  pings so clients refetch their own permission-filtered slice), and the CRDT
  relay. Presence is WS-level state only: no event, no REST, no migration.
  Single-worker is the default; **multi-worker is opt-in** (`WEB_CONCURRENCY>1`,
  Redis required) and adds a cross-worker broadcast relay + TTL presence store so
  rooms span workers, plus a scheduler sidecar (ADR-0025/0026, #189).
- **Competitions** — the tenancy root. Team or individual mode, visibility,
  invite codes, schedule, a **status gameplay gate** (`not_started`/`running`/
  `ended`, default not-started — competitor challenge/scoreboard access is open
  only while running; manual Start/Stop under `manage_schedule` + schedule
  auto-drive it, ADR-0028), **pause**, archive (with an opt-out retention policy
  that auto-purges), clone, hard delete, rules/CoC gate, brackets, and a
  per-competition managed vocab for tags/difficulty.
- **Challenges & scoring** — static / regex / multiple-choice flags; static or
  **dynamic (decay)** scoring; prerequisites; scheduled release; hints; guess
  caps with non-destructive resets; bulk ctfcli-YAML import/export. The
  scoreboard supports **freeze** (a read-path filter plus an event), brackets, a
  public spectator board with insights, and a CTFtime feed.
- **Automation** — the §5 engine on the background lane, catalog-driven
  (`utils/automation_catalog.py`) so a new action is a backend-only change that
  the visual builder picks up automatically. Webhook egress is hardened per
  ADR-0013. Triggers are permission-governed (`TRIGGER_PERMISSIONS`).
- **Collaboration** — Y.js CRDT under TipTap, transported as a **dumb relay**
  with client-snapshot persistence (ADR-0014). The server never decodes the CRDT.
- **Admin** — users directory + soft-ban, custom role editor, site-wide theming
  and branding (custom logo in the DB, not object storage), SMTP, cross-
  competition audit log, a site overview, and a full **export/import backup**
  (ADR-0016 — additive, carries secrets, so the file is sensitive).
- **AI assistants** — the optional `ai` module (ADR-0023): an administrator
  assistant and an audience-aware competitor assistant over an operator-
  configured OpenAI-compatible provider. Ships **inert** — the site master
  switch (`ai_settings.enabled`) defaults off, so nothing calls out until an
  admin configures + enables it, and no other feature may depend on it. Off by
  default; carries chat content (`PRIVACY.md`).
- **Frontend** — Next.js App Router. One hook module per domain in
  `src/lib/hooks/` (~32 of them); components never touch `@/lib/api` directly
  (ESLint-enforced). Auth screens, `/setup`, `/public/*` and the password/email
  flows live **outside** the `(app)` shell.

## Things that will bite you

Hard-won, non-obvious, and not visible from reading the code you're changing.

- **Commit before emitting.** The audit consumer opens its **own** DB session,
  so emitting while your transaction is still open deadlocks on the SQLite
  writer lock — this cost 10 seconds per request once before it was found.
  Commit, then emit.
- **`models/__init__.py` must import every model.** The test suite builds the
  schema from `Base.metadata`; a model reachable only by import side-effect
  gets no table, and you get a "no such table" 404 that reproduces only in
  isolation.
- **Migrations aren't covered by the test suite** (schema comes from
  `Base.metadata`, ADR-0006), and SQLite accepts things Postgres rejects (e.g.
  `SET boolcol = 1` — Postgres needs `TRUE`). A migration bug surfaces only
  against real Postgres: bring `docker compose up` up at least once before
  shipping one. CI has a Postgres migrations job that will catch you otherwise.
- **`npm run build` is part of the frontend gauntlet.** tsc, eslint and vitest
  miss build-only failures. Caveat: since i18n (ADR-0029) every route renders
  dynamically, so the build no longer exercises prerendering and the old
  missing-Suspense-boundary failure can't fire. Keep the Suspense boundaries
  anyway — they're load-bearing again the moment any route goes static.
- **Y.js must be a single instance**, or collaborative editing breaks in ways
  that look like data corruption. This was pinned by a webpack alias in
  `next.config.mjs`; it isn't any more (#159). Next 16 builds with Turbopack,
  which ignores the `webpack` hook without warning, and whose `resolveAlias`
  was measured not to apply here either. What holds it today is an ESM-only
  client graph plus one `yjs` in the lockfile — emergent, so it is enforced
  rather than assumed: `npm run build` runs
  `frontend/scripts/check-yjs-singleton.mjs`, which fails the build on more
  than one copy in the emitted chunks.
- **A frontend dependency change needs `--renew-anon-volumes` in the dev stack.**
  `docker-compose.dev.yml` mounts `/app/node_modules` as an anonymous volume to
  shadow the bind mount, and `up --build` **reuses** it — so the image rebuilds
  but the container keeps the old packages and quietly runs a different version
  from `package.json` (during the Next 16 bump the container still reported
  Next 15). Use `up -d --build --renew-anon-volumes frontend`, and confirm with
  `exec frontend node -e "console.log(require('next/package.json').version)"`.
- **Object storage has no local-filesystem backend.** `get_storage()` needs
  MinIO, so the zero-infra SQLite preview stack needs
  `docker compose -f docker-compose.dev.yml up -d minio` before any attachment
  upload works (config defaults to `localhost:9000`).
- **`PUBLIC_BASE_URL` is required behind a TLS-terminating proxy.** uvicorn runs
  without `--proxy-headers`, so a request-derived OIDC `redirect_uri` says
  `http://` and the IdP rejects the mismatch.
- **`OIDC_ALLOW_INSECURE_ISSUERS` disables the https requirement *and* the SSRF
  blocklist.** It exists so a localhost mock IdP works in dev. Never production.
- **Bulk operations emit no per-row events** — challenge YAML import and backup
  import are atomic authoring ops, deliberately not a flood of
  `challenge.created`.
- **`conftest` drains `event_bus.wait_for_background()` before `drop_all`**, or
  fire-and-forget automation tasks leak across the per-test schema and flake
  unrelated tests.

## Setup, dev, and demo

**There is no seeded default admin in production** (ADR-0017, superseding
ADR-0010). A fresh install ships with **no** administrator and is *unconfigured*
until an operator completes the **first-run setup wizard** (`/setup`), which
creates the owner account and initial branding.
`auth.setup.instance_needs_setup` (no active Administrator ⇒ true) gates the
wizard and blocks public registration until an owner exists; `SetupGuard`
redirects while unconfigured. Public registration never grants above
Participant. **The test suite still seeds `admin@example.com` / `changeme`** in
its fixtures (`auth/seed.py` constants), so `admin_token` works unchanged.

`.claude/launch.json`'s backend config runs against **SQLite** by default
(`DATABASE_URL` overrides) so `preview` needs no infra, matching the test stack
(ADR-0006). Migrations run automatically on every start — **restart** the
backend rather than reloading after adding a migration or a new module.

**Demo mode** (`config.demo_mode`, env `DEMO_MODE`) is for the public demo
instance (demo.flagpost.io). It seeds well-known accounts
(`admin`/`judge`/`participant`, password `password`) plus a sample competition
(`auth/demo.py`, idempotent), exposes `demo_mode` on the public
`GET /api/site-settings` (driving the banner + login credentials card), disables
outbound automation actions (`DEMO_DISABLED_ACTIONS`), and **suppresses the
update check** (an hourly reset would inflate the adoption count ~24×). The
hourly reset itself is external. **Never enable it on a real deployment** — it
seeds public credentials.

A separate **activity simulator** (`backend/demo_simulator.py`, the `simulator`
service in `docker-compose.demo.yml`) drives realistic API traffic so the demo
looks live. It's demo-guarded (refuses unless the target reports `demo_mode`,
plus `DEMO_SIMULATOR=1`), uses only throwaway bot accounts, and touches only
bot-opened tickets. Its answers live in `auth/demo_data.py`, **shared with the
seed**, so the two can't drift.

**Outbound calls** are only: operator-configured SMTP/webhooks, external
identity-provider traffic (OIDC / SAML / LDAP), the operator-configured AI
provider endpoint when the optional AI
assistant is enabled (off by default; carries chat content — `PRIVACY.md`), and
one daily version-only update check (`PRIVACY.md`, §13.4). Nothing else phones
home — keep it that way.

## Read the ADR before touching

`docs/adr/` — 33 records, indexed in `docs/adr/README.md`. The ones most likely
to matter:

| Area | ADR |
|---|---|
| Refresh sessions / token storage | 0008 |
| Emitting events, sync vs background | 0012 (supersedes 0009) |
| Webhook egress hardening | 0013 |
| CRDT transport & persistence | 0014 |
| Theming scope | 0011 (site-wide only) |
| Identity: usernames, optional email | 0015 |
| Export/import backup | 0016 |
| Setup wizard / no default admin | 0017 (supersedes 0010) |
| Regex-flag ReDoS containment | 0018 |
| Per-install JWT secret | 0019 |
| Storing secrets (hash vs encrypt) | 0020 — facility is `utils/crypto.EncryptedString` |
| OIDC identity framework | 0021 |
| External auth: SAML + LDAP | 0022 |
| Plain-OAuth2 kind (GitHub/Discord), userinfo as identity | 0033 |
| AI assistant provider & execution model | 0023 |
| Built-in SSO provider presets (Google/Microsoft) | 0024 |
| Multi-worker relay & cross-worker presence | 0025, 0026 |
| Multi-instance / Fargate+ALB deployment flags | 0031 |

If an ADR's decision looks wrong for what you're building, say so and propose a
new one — don't quietly work around it.

**Standing scope notes** (owner decisions): the challenge lifecycle
(ROADMAP item 17) is deferred and unscheduled, and theming is **site-wide only**
(ROADMAP item 20, ADR-0011).

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

- Plugin marketplace / third-party modules — the module *mechanism* is
  used for required-core features starting in Tier 0, but the
  marketplace path (listing/discovery + untrusted-code sandboxing) stays
  closed.
- Multi-competition tenancy *consolidation views* — `competition_id`
  scoping is required from Tier 0; cross-site rollups are not.
- Per-competition / white-label theming — site-wide only for now
  (ADR-0011); the per-competition variant may return later.

Note: the **automation engine**, **dashboard drag-and-drop**,
**collaborative rich-text/CRDT editing**, **SAML/LDAP** (#100/#101, ADR-0022),
and the **AI assistants** module (#98, ADR-0023) were all on this list once and
have **shipped** — don't treat them as deferred. External auth is now OIDC +
SAML + LDAP, one `IdentityProvider` framework; a new protocol is a new `kind`,
not a fork.

## Stack

Fixed by `docs/ARCHITECTURE.md` §2 — don't substitute an alternative to
something already decided there (e.g. Zustand + TanStack Query, not
Redux; SQLAlchemy 2.x async, not a different ORM).

```
# Whole PRODUCTION stack (Caddy + backend + frontend + Postgres/Redis/MinIO).
# Caddy fronts everything single-origin; the backend runs `alembic upgrade head`
# before serving, so the DB is migrated + roles seeded on first boot.
docker compose up --build            # app on http://localhost:8080
# DEV stack (hot reload, source-mounted, dev servers):
docker compose -f docker-compose.dev.yml up --build   # frontend :3000, backend :8000

# Backend only (needs a venv — this host's Python is externally-managed)
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head          # against a reachable Postgres
.venv/bin/uvicorn main:app --reload

# Frontend only — REQUIRES Node 20+ (Tailwind v4's engine, @tailwindcss/oxide).
# CI and the shipped images run Node 26 / Python 3.14.
cd frontend && npm install && npm run dev
```

## Code conventions

- Backend: Pydantic schemas (`backend/schemas/`) are separate from
  SQLAlchemy models (`backend/models/`) — never return a model directly
  from a route.
- Backend: one FastAPI router per domain (`backend/routers/`), mirroring
  the one-hook-per-domain convention on the frontend.
- Frontend: server state through TanStack Query hooks only; Zustand is
  for client/UI state (auth, active competition, prefs) — don't put
  server data in a Zustand store.
- Frontend i18n (ADR-0029, extraction in progress): in a domain already
  extracted to next-intl (the file imports `useTranslations`), new
  user-facing strings go through `messages/en.json` + `t()`, not literals.
  **Every *new* page/surface is born extracted** (owner decision,
  2026-08-18): its user-facing strings go into `frontend/messages/en.json`
  + `t()` from the first commit — Crowdin's source is exactly that file
  (`crowdin.yml`), so a page shipped as literals is invisible to
  translators and silently grows the untranslated backlog. *Existing*
  unextracted domains keep literals until their own extraction PR — don't
  half-extract. Components under an intl'd tree need `renderWithIntl`
  (`src/test/intl.tsx`) in tests.
- Migrations: `YYYY-MM-DD_<revid>_<desc>.py`, one migration per PR. Never
  hand-edit a migration that's already been applied anywhere.

## Git workflow

Unless the user says otherwise, **a feature is built on its own branch, not
`main`**: branch from `main`, do the work, and once it's finished and the
five-check gauntlet passes, commit and open a PR (`gh pr create`) — don't push a
feature to `main` directly. Merge only once CI is green. (A trivial inline
fix/typo the user asks for is the "otherwise".)

## Testing

Established in Tier 0 (see `docs/adr/0006-testing-stack.md`):

- **Backend:** pytest + pytest-asyncio, httpx ASGI transport, SQLite
  (aiosqlite) so no infra is needed. `cd backend && .venv/bin/pytest`.
  The suite builds the schema from `Base.metadata` and seeds roles from
  `auth/seed.py` (the same specs the migration uses).
  **Test-created competitions auto-start** — an autouse `conftest` fixture flips
  each to `running` (via a `competition.created` listener) so gameplay tests
  aren't blocked by the #221 status gate. A test that needs the real
  `not_started` default marks itself `@pytest.mark.competition_lifecycle`.
  **Argon2 runs at a reduced cost under test** (`conftest` sets
  `ARGON2_MEMORY_COST`/`ARGON2_TIME_COST`): a fresh admin is hashed per test, so
  production params cost ~3.5 min of a run. Don't read hashing *speed* off the
  suite, and don't relax `argon2_parallelism` — p=1 is a correctness property
  (#207). The shipped defaults are pinned by
  `test_hash_executor.test_production_argon2_defaults_are_strong`.
- **Frontend:** Vitest + Testing Library + jsdom.
  `cd frontend && npm run test`.

Keep SQLite/Postgres differences in mind (models stay portable, generic
`JSON`, `render_as_batch` migrations) — the ADR spells out the tradeoff.

The full gauntlet CI runs, in order — **all five**, and `npm run build` is
not optional (see "Things that will bite you"):

```bash
cd backend  && .venv/bin/pytest
cd frontend && npx tsc --noEmit && npx eslint . && npm run test && npm run build
```

## Keeping this file honest

If you catch yourself re-explaining the same thing twice in a session, or
a rule here turns out to be wrong, fix it here. If it's a real
architectural decision (not just a typo), update `docs/ARCHITECTURE.md`
and/or add an ADR too — don't let this file and the real docs drift apart.

**This file is orientation, not a changelog.** It was once an append-only
build log that grew past 900 lines, most of it restating what git history,
the ADRs and `ARCHITECTURE.md` already recorded — and it still drifted,
because nobody rereads 900 lines to check. So: when you ship something,
resist adding a paragraph here. Ask instead whether it belongs in
`ARCHITECTURE.md` (a design fact), an ADR (a contested decision), the
`ROADMAP.md` milestone summary (what shipped), or "Things that will bite
you" above (a trap the code doesn't reveal). If none of those fit, it
probably doesn't need writing down at all.