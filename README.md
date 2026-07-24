# Flagpost

Flagpost is a modern, open-source CTF competition management platform.

- **What & why:** [`docs/VISION.md`](docs/VISION.md)
- **How (binding technical design):** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Build order:** [`docs/ROADMAP.md`](docs/ROADMAP.md)
- **Why past decisions were made:** [`docs/adr/`](docs/adr/)

## What it does

A full competition lifecycle, multi-tenant from the ground up (every event is
scoped to a competition):

- **Competitions** — team or individual mode, public/private, schedule, pause,
  archive, clone, and per-competition module toggles.
- **Challenges** — categories, static / regex / multiple-choice flags, dynamic
  (decay) scoring, hints, file attachments, prerequisites (unlock chains),
  scheduled release, tags & difficulty, per-competition guess caps, and bulk
  ctfcli-format YAML import/export.
- **Scoring & scoreboard** — live over WebSocket, first blood, freeze, brackets/
  divisions, a public spectator board, and a CTFtime feed.
- **Teams & participants** — invite codes, optional captain approval, size caps,
  rosters, and manual judge awards.
- **Support tickets, announcements, live presence, and collaborative notes**
  (CRDT) on challenges and tickets.
- **Automation engine** — a visual When → If → Then rule builder with SSRF-
  hardened webhooks, email, in-app notifications, and time-based triggers.
- **Feedback surveys & challenge ratings, challenge/team analytics, and an
  operational dashboard** with drag-and-drop widgets.
- **Administration** — users, a data-driven roles/permissions editor, site-wide
  theming and branding (custom logo), SMTP, a full-fidelity export/import
  backup, and a cross-competition event/audit log.

Password auth only for now; SSO/LDAP and an AI assistant are deliberately
deferred (see the "Explicitly Deferred" section of `docs/ROADMAP.md`).

## First run

A fresh install ships with **no administrator** — it's *unconfigured* until an
operator completes the one-time **setup wizard** at `/setup`, which creates the
owner account (no hard-coded credentials) and the initial branding (ADR-0017).
Public registration is blocked until an owner exists and never grants above
Participant.

## Running locally (dev / demo)

Requires Docker with Compose. This stack runs the dev servers (`next dev`,
`uvicorn --reload`) against Postgres/Redis/MinIO — it's for local development
and evaluation, **not** a production deployment (see below).

```bash
cp .env.example .env      # optional; defaults work as-is for local
docker compose up --build
```

| Service       | URL                                            |
|---------------|------------------------------------------------|
| Frontend      | http://localhost:3000                          |
| Backend API   | http://localhost:8000/docs                     |
| MinIO console | http://localhost:9001 (minioadmin/minioadmin)  |

Open the frontend and complete the setup wizard to create the owner account.

## Deploying to production

The shipped compose is a dev stack; a real deployment must additionally:

- Set a strong **`JWT_SECRET`** (the app derives and persists a per-install
  secret if you don't, but set one explicitly for multi-host — see
  `backend/config.py`).
- Point **`NEXT_PUBLIC_API_URL`** at the browser-reachable backend URL (it's
  baked into the frontend at build time), and set **`CORS_ORIGINS`** to your
  frontend origin.
- Use real credentials for Postgres, Redis, and MinIO/S3, and serve behind TLS.
- Build and serve the frontend for production (`next build && next start`) and
  run the backend under a production process manager rather than `--reload`.

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
