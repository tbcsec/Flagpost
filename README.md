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

## Quick start (Docker)

Requires Docker with Compose. The default stack is **production** — built
images, a Caddy reverse proxy fronting everything on one origin, Postgres, Redis,
and MinIO:

```bash
cp .env.example .env      # optional; defaults run as-is locally
docker compose up --build
```

Open **http://localhost:8080** and complete the setup wizard to create the owner
account. That's it — the app, its API, and its live WebSocket updates are all
served same-origin through Caddy, so there's nothing else to configure for a
local run.

## Deploying to production

The default compose *is* the production stack, so a real deployment is mostly
configuration in `.env`:

- **`SITE_ADDRESS`** — your domain (e.g. `ctf.example.com`). Caddy obtains and
  renews TLS automatically. Map ports `80` and `443`.
- **`PUBLIC_ORIGIN`** — the browser-facing origin (e.g. `https://ctf.example.com`).
  It's baked into the frontend at build time, so set it before `docker compose
  build`.
- **`JWT_SECRET`** — a long random value (required for multi-host; otherwise the
  app derives and persists one in a volume).
- Real **Postgres / MinIO credentials**, and `MINIO_PUBLIC_ENDPOINT` pointing at
  a browser-reachable MinIO host for attachment downloads.

The backend runs as a single process by design (the WebSocket layer is
in-process — ADR-0005). To run **without Docker in production**: build and serve
the frontend with `npm run build && npm run start`, and run the backend with
`alembic upgrade head` then `uvicorn main:app` (no `--reload`) behind your own
TLS-terminating proxy.

## Local development (hot reload)

For iterating on the code, the dev stack mounts source and runs the dev servers:

```bash
docker compose -f docker-compose.dev.yml up --build
# frontend → http://localhost:3000   backend → http://localhost:8000/docs
```

Or run each side directly (see "Running each side without Docker" below).

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

## License

Copyright (C) 2026 Tom Collier.

Flagpost is free software: you can redistribute it and/or modify it under the
terms of the **GNU Affero General Public License** as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version.

It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
PURPOSE. See the full [`LICENSE`](LICENSE) for details.

The AGPL's network-use clause (§13) means anyone running a **modified** Flagpost
as a network service must offer its source to users. The built-in, non-removable
"Powered by Flagpost" footer links every page to this repository, which is how
Flagpost surfaces its source to remote users as §13 anticipates.
