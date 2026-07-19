# Tier 0 — Foundation: Implementation Plan

## Context

The repo currently contains the verified hello-world skeleton (commit `4b5bf50`): FastAPI backend, Next.js frontend, docker-compose with Postgres/Redis/MinIO, and the empty §14 directory tree. Nothing from Tier 0 exists yet.

This plan implements all five Tier 0 items from `docs/ROADMAP.md` (Auth & RBAC, Competition entity & scoping, Design system/tokens, Event bus, Domain hook layer), governed by `docs/ARCHITECTURE.md` §2–§9 and ADRs 0001–0005. One commit per phase, in dependency order.

**Decisions already fixed by docs (not revisited):** app-level `competition_id` tenancy (ADR-0001), JWT access + httpOnly refresh cookie (ADR-0003), roles-as-data with seeded system roles (ADR-0004), in-process async event bus (ADR-0005), Tailwind v4 `@theme` tokens + shadcn-style primitives (§9), TanStack Query + Zustand (§8).

**Decisions made in planning:**
- **Build order deviates from roadmap numbering**: event bus first (roadmap #4) because auth mutations must emit `user.registered` — "every mutation emits an event" requires the bus to exist before the first mutation.
- **Module loader deferred to Tier 1 start**: it's kernel per ADR-0002, but ROADMAP deliberately omits it from Tier 0 and its first real consumer is Challenges (Tier 1 #8). Building it now with zero consumers risks a wrong abstraction. Noted in CLAUDE.md at wrap-up.
- **First registered user becomes Administrator** (user's choice). Only when the users table is empty; logs a prominent warning. Public registration otherwise never grants beyond Participant.
- **Refresh tokens are DB-backed** (hashed, rotated) so logout/revocation actually works — ADR-0003 is silent on revocation; "produces a `current_user` and a session" (§7.7) implies a session row.
- **New event type**: `competition.created` must be added to §3.2's vocabulary (docs edit) before code emits it — per CLAUDE.md rule.
- **Testing**: pytest + pytest-asyncio (backend, SQLite in-memory via aiosqlite — keeps column types portable), Vitest + Testing Library (frontend). Recorded as **ADR-0006** per CLAUDE.md's instruction.

---

## Phase A — Backend core plumbing + event bus

New deps (`backend/requirements.txt`): `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `aiosqlite` (tests), `pyjwt`, `pwdlib[argon2]`, `pydantic[email]`, `httpx` + `pytest` + `pytest-asyncio` (dev — split into `requirements-dev.txt`).

- `backend/db.py` — async engine from `settings.database_url`, `async_sessionmaker`, `Base` (DeclarativeBase with naming conventions), `get_db` FastAPI dependency, and a `CompetitionScopedMixin` (non-nullable `competition_id` FK) establishing the §6.2 pattern.
- `backend/utils/event_bus.py` — `EventBus` per §3.1/ADR-0005: `on(pattern)` decorator with `*` wildcards, `emit()` dispatches via `asyncio.create_task` (never blocks the request), per-handler try/except + logging (isolated failure), per-handler timeout (ADR-0005's flagged cost), optional `owner` tag on registration (plugin detach later). Module-level `event_bus` singleton.
- `backend/models/audit_log.py` + `backend/utils/audit_log.py` — `AuditLogEntry` (id, event_name, payload JSON, competition_id nullable, user_id nullable, created_at); a wildcard `*` subscriber persisting every event. The bus's only consumer for now (ROADMAP #4).
- Alembic: async-template init under `backend/alembic/`, `file_template` configured for `YYYY-MM-DD_<revid>_<desc>` naming. **Migration 1**: audit_log table.
- Tests: `backend/tests/` — event bus (wildcards, isolation, non-blocking, timeout), audit subscriber writes a row.
- `docs/adr/0006-testing-stack.md` (pytest + Vitest, follows `docs/adr/template.md`).

## Phase B — Auth & RBAC (kernel)

- `backend/auth/permissions.py` — the categorized permission catalog from §7.1, verbatim, each with `scope: global|competition`. `backend/tests` include ADR-0004's suggested guard: every `require_permission("x")` call site references a catalog key (grep-based test).
- Models: `User` (email unique, password_hash, display_name, created_at), `Role` (§7.2 shape, permissions as JSON array), `RoleAssignment` (§7.5: user_id, competition_id nullable, role_id), `RefreshSession` (user_id, token_hash, expires_at, revoked_at).
- `backend/auth/security.py` — argon2 hashing (pwdlib); JWT access tokens (15 min, `sub` + token version) via PyJWT; refresh issue/rotate/revoke against `RefreshSession`.
- `backend/auth/deps.py` — `get_current_user` (Bearer header) and `require_permission(key)` per §7.6: resolves the user's role for the request's competition context (global roles for global-scope permissions), 403 otherwise.
- `backend/routers/auth.py` — `POST /api/auth/register` (emits `user.registered`; first-ever user gets the Administrator global RoleAssignment + warning log), `POST /api/auth/login` (sets httpOnly refresh cookie, returns access token), `POST /api/auth/refresh` (rotates), `POST /api/auth/logout` (revokes), `GET /api/auth/me`. Pydantic schemas in `backend/schemas/auth.py` — never return models directly.
- **Migration 2**: users/roles/role_assignments/refresh_sessions + seed the three `is_system` roles (Administrator: full catalog; Judge: competition-scoped operational set; Participant: competitor-facing set — per §7.3).
- Tests: full register→login→me→refresh→logout flow (httpx ASGI), first-user-admin bootstrap, `require_permission` 403/200, cookie flags (httpOnly).

## Phase C — Competition entity & scoping

- Docs edit first: add `competition.created` to §3.2's vocabulary in `docs/ARCHITECTURE.md`.
- `backend/models/competition.py` — id (uuid), name, description, start_at/end_at, `participation_mode: 'team'|'individual'` (§11.3), created_at. **Migration 3**.
- `backend/routers/competitions.py` + `backend/schemas/competition.py` — list/get (authenticated), create (`require_permission("create_competition")`, emits `competition.created`), update (`edit_competition`). Data-access helpers take `competition_id` as a required parameter — establishing the §6.2 discipline for every later domain.
- Tests: create emits event + audit row; permission enforcement; participant cannot create.

## Phase D — Design system / token layer (frontend)

New deps: `tailwindcss@4`, `@tailwindcss/postcss`, `class-variance-authority`, `clsx`, `tailwind-merge`, `@radix-ui/react-dialog`, `@radix-ui/react-label`.

- `frontend/src/app/globals.css` — §9 token layer: HSL custom properties, `@theme` mapping (`--color-primary: hsl(var(--primary))` …), palettes switched by `data-palette` on `<html>` (default dark + light to start), `@custom-variant dark`.
- `frontend/src/components/ui/` — the five roadmap primitives in shadcn style on top of tokens: `button.tsx`, `input.tsx`, `card.tsx`, `dialog.tsx`, `table.tsx` (+ `label.tsx`, `lib/utils.ts` `cn()` helper).
- Replace the placeholder inline styles in `layout.tsx` / `page.tsx` with token classes (removes the scaffold's marked stopgap).

## Phase E — Domain hook layer + auth UI (frontend)

New deps: `@tanstack/react-query`, `zustand`; dev: `vitest`, `@testing-library/react`, `jsdom`.

- `frontend/src/lib/api.ts` — real client: base fetch with Bearer header from the auth store, single-flight 401→refresh→retry, typed helpers. Components still never import it directly (§8).
- `frontend/src/app/providers.tsx` — QueryClientProvider (staleTime 60s, `refetchOnWindowFocus: false` per §8), wired in `layout.tsx`.
- `frontend/src/stores/auth.ts` — Zustand: access token (memory only), current user snapshot, active competition id. No server data beyond the session identity (§2 conventions).
- `frontend/src/lib/hooks/use-users.ts` — register/login/logout mutations, `useMe()`. `use-competitions.ts` — `['competitions', …]`-keyed list/get + create mutation invalidating its own domain only.
- Pages: `/login`, `/register` (design-system primitives), home page becomes: signed-out → login prompt; signed-in → competitions list (+ create dialog when permitted). This is the Tier 0 end-to-end demo — auth, RBAC, tokens, hooks all exercised.
- Vitest: config + tests for auth store logic and one component render.

## Phase F — Wrap-up

- docker-compose backend command: `alembic upgrade head && uvicorn …` so `docker compose up` migrates dev DBs automatically.
- Update `.claude/CLAUDE.md` (stage line → Tier 0 built; note module-loader deferral to Tier 1), `README.md` current-state.
- Full verification (below), then final commit.

---

## Verification

1. `cd backend && pytest` — all backend suites green.
2. `cd frontend && npx vitest run` — frontend tests green.
3. `docker compose up --build`: register first user via UI → warning logged, user is Administrator → create competition via UI dialog → appears in list; second registered user is Participant and gets 403 on create (checked via curl).
4. `docker compose exec postgres psql … -c 'select event_name from audit_log'` shows `user.registered` / `competition.created` rows — proves bus + audit consumer.
5. Native dev servers (`.claude/launch.json`) still start; preview the login flow.

## Out of scope (explicitly not in this plan)

Module loader (Tier 1 start), teams, challenges, WebSocket layer, MinIO/Redis client code, custom-role editor UI, SSO — all later tiers per ROADMAP.
