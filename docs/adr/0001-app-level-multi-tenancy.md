# ADR-0001: App-level multi-competition tenancy, not schema-per-competition

**Status:** Accepted
**Date:** 2026-07-17
**Architecture reference:** `ARCHITECTURE.md` §6

## Context

A single deployment needs to host many competitions at once, fully
segregated from each other's data, rather than requiring one deployment
per competition. The clearest driver is globally distributed events: a
multi-site competition where each physical site currently needs its own
separate scoreboard instance should be able to run as one deployment,
with each site modeled as its own competition — while still supporting a
global admin view that rolls up standings or challenge-health across
sites.

Two real options existed for enforcing that segregation:

1. **Schema-per-competition** — each competition gets its own Postgres
   schema (or database), giving strong physical isolation "for free."
2. **App-level scoping** — a single schema, every tenant-scoped table
   carries a `competition_id` foreign key, and every query/router
   enforces that scoping consistently at the data-access layer.

## Decision

Enforce tenancy at the **application level** (`competition_id` scoping),
not via per-competition database schemas.

## Consequences

- Positive: cross-site rollups — the entire point of the multi-site use
  case — are a single filtered query instead of a fan-out across N
  schemas. This is the deciding factor: schema-per-competition would
  make the feature that motivated multi-tenancy in the first place
  *harder*, not easier.
- Positive: the event bus and automation engine already carry
  `competition_id` on their payloads/rules, so this scoping is additive
  to work already done, not a parallel system to maintain.
- Negative / cost: isolation is only as strong as every query and router
  consistently applying the scope — a missed check is a cross-tenant
  data leak, not a schema-boundary error the database would catch for
  free. This has to be a cross-cutting concern enforced at the
  data-access layer (§8), not left to individual endpoints to remember.
- Forecloses: true physical/credential isolation between competitions at
  the database level (relevant if a future customer needs a hard
  compliance boundary between tenants, not just a UI-level one). If that
  requirement appears, it's a new ADR, not a reversal of this one — the
  two approaches aren't mutually exclusive at the deployment level.
