# Flagpost

Flagpost is a modern, open-source CTF competition management platform.

- **What & why:** [`docs/VISION.md`](docs/VISION.md)
- **How (binding technical design):** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Build order:** [`docs/ROADMAP.md`](docs/ROADMAP.md)

## Current state

**Tier 0 (Foundation) — built.** On top of the scaffold, the kernel and Tier
0 foundations now exist (see `docs/ROADMAP.md`):

- **Event bus** (async pub/sub) with an audit-log consumer persisting every
  event.
- **Auth & RBAC** — JWT access tokens + httpOnly refresh cookies, argon2
  passwords, and roles/permissions as data with the three built-in roles.
  The first account registered on a fresh install becomes the administrator.
- **Competition entity** — the multi-tenant root every later entity scopes to.
- **Design system** — a Tailwind v4 `@theme` token layer (dark + light
  palettes) with shadcn-style primitives.
- **Frontend data layer** — TanStack Query hooks per domain + a Zustand auth
  store, with login/register and an authenticated competitions view.

Tier 1 (a live, end-to-end competition) is next.

## Running locally

Requires Docker with Compose.

```bash
cp .env.example .env      # optional; defaults work as-is
docker compose up --build
```

Then:

| Service       | URL                                   |
|---------------|---------------------------------------|
| Frontend      | http://localhost:3000                 |
| Backend API   | http://localhost:8000/api/hello       |
| API docs      | http://localhost:8000/docs            |
| MinIO console | http://localhost:9001 (minioadmin/minioadmin) |

Open the frontend, **register an account** (the first one becomes the
administrator), then create a competition — it appears in the list, and the
`user.registered` / `competition.created` events land in the `audit_log`
table.

## Layout

```
backend/    FastAPI app + the §14 package tree (models, schemas, routers,
            utils, plugins, alembic)
frontend/   Next.js App Router app + the §14 src tree (app, components,
            lib/hooks, stores)
docs/       Vision, architecture, roadmap, and ADRs
```

## Running each side without Docker

```bash
# Backend — the host Python is externally-managed, so use a venv
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head        # against a reachable Postgres
.venv/bin/uvicorn main:app --reload

# Frontend — REQUIRES Node 20+ (Tailwind v4's @tailwindcss/oxide engine)
cd frontend && npm install && npm run dev
```

## Tests

```bash
cd backend && .venv/bin/pytest        # pytest, SQLite-backed, no infra needed
cd frontend && npm run test           # vitest
```
