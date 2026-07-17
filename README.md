# CTF Platform

A modern, open-source CTF competition management platform.

- **What & why:** [`docs/VISION.md`](docs/VISION.md)
- **How (binding technical design):** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Build order:** [`docs/ROADMAP.md`](docs/ROADMAP.md)

## Current state

**Tier 0 skeleton.** This repo currently contains only the scaffold: the
directory structure from ARCHITECTURE.md §14, a hello-world FastAPI backend,
a hello-world Next.js (App Router) frontend that fetches from it, and a
docker-compose stack wiring Postgres, Redis, and MinIO. No Tier 0 feature
(auth, event bus, design tokens, …) is built yet — see `docs/ROADMAP.md`.

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

The frontend homepage fetches `/api/hello` from the backend and renders the
message — if you see it, the two sides are talking.

## Layout

```
backend/    FastAPI app + the §14 package tree (models, schemas, routers,
            utils, plugins, alembic) — empty until features land
frontend/   Next.js App Router app + the §14 src tree (app, components,
            lib/hooks, stores)
docs/       Vision, architecture, roadmap, and ADRs
```

## Running each side without Docker

```bash
# Backend
cd backend && pip install -r requirements.txt && uvicorn main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```
