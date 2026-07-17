# ADR-0006: Testing stack — pytest (backend) + Vitest (frontend)

**Status:** Accepted
**Date:** 2026-07-17
**Architecture reference:** `CLAUDE.md` "Testing"; `ROADMAP.md` Tier 0

## Context

`CLAUDE.md` records that a testing approach is "not yet established" and
explicitly asks that whoever sets it up during Tier 0 propose pytest
(backend) and Vitest (frontend) and record the decision as an ADR rather
than picking it silently mid-PR. Tier 0 is the first code with behaviour
worth testing (the event bus's isolation/timeout guarantees, RBAC
enforcement), so the decision can't be deferred further.

The real options were the conventional ones for this stack: on the
backend, pytest vs. the stdlib `unittest`; on the frontend, Vitest vs.
Jest. The backend is async-first (SQLAlchemy 2.x async, FastAPI), and the
frontend is Vite-adjacent via Next.js, which biases both choices.

## Decision

- **Backend:** pytest + `pytest-asyncio` (async test functions), with
  `httpx.ASGITransport` for in-process API tests and `aiosqlite` for a
  file-backed SQLite database so the suite needs no running Postgres.
  Schema is created per-test from `Base.metadata`.
- **Frontend:** Vitest + `@testing-library/react` + jsdom.

## Consequences

- Positive: pytest-asyncio matches the async codebase directly; httpx
  ASGI transport tests the real app without binding a port; SQLite keeps
  the suite fast and infra-free for CI and local runs.
- Positive: Vitest reuses the Vite/ESM toolchain the frontend already
  implies, so no separate Babel/Jest transform config to maintain.
- Negative / cost: SQLite is not Postgres — dialect-specific behaviour
  (JSONB operators, `citext`, certain constraints) won't be exercised by
  the default suite. Mitigated by keeping models portable (generic `JSON`,
  `render_as_batch` migrations) and leaving room for a Postgres-backed
  integration tier later if a feature depends on PG-specific behaviour.
- Forecloses: nothing hard — a Postgres test profile can be added
  alongside this without replacing it. This ADR sets the default, not the
  ceiling.
