# ADR-0009: Event dispatch is synchronous (awaited) in Tier 0

**Status:** Accepted
**Date:** 2026-07-18
**Architecture reference:** `ARCHITECTURE.md` §3.1 (refines ADR-0005)

## Context

§3.1 and ADR-0005 specify that emitting an event is **non-blocking**:
"slow handlers (e.g. an outbound webhook) don't hold up the API response."
The Tier 0 event bus does not yet honour that property — `emit()` awaits
`asyncio.gather(...)` over all matching handlers, so the request that
triggered the event blocks until every handler finishes (bounded by a
per-handler timeout).

This surfaced during the Tier 0 review as a code/spec divergence, so it's
recorded here deliberately rather than left silent (per `CLAUDE.md`, a
code/`ARCHITECTURE.md` disagreement is a bug in one of them, not something
to work around quietly).

The reason the divergence is currently benign — and arguably preferable —
is that Tier 0's *only* consumer is the audit-log subscriber: a fast,
local DB write. Awaiting it means the audit row is committed before the
response returns (stronger durability), and it keeps tests deterministic
("emit, then assert the row exists" has no race). Implementing true
fire-and-forget now would make the audit log lossy on a mid-dispatch crash
and make those tests racy, for no present benefit — there are no slow
handlers to protect the response from.

## Decision

For Tier 0, `emit()` awaits all matching handlers rather than scheduling
them fire-and-forget. This is a deliberate, temporary divergence from
§3.1's non-blocking property, scoped to the period where the audit log is
the only consumer.

## Consequences

- Positive: audit durability (the event is persisted before the response)
  and deterministic tests, with per-handler isolation + timeout already in
  place to bound the cost of any single misbehaving handler.
- Negative / cost: the API response waits for handlers, so this **must**
  change before the first genuinely slow or external handler ships — the
  automation engine's outbound `webhook` action (§5.3) is the concrete
  trigger. Until then, "non-blocking emit" is aspirational in the code,
  not real, and anyone relying on that §3.1 property should treat it as
  not-yet-true.
- Forecloses: nothing permanently. The eventual model — fire-and-forget
  dispatch with an outbox for durable async delivery, and/or a split
  between sync-critical handlers (audit) and async-background handlers
  (webhooks/notifications) — is left open in §15. This ADR refines only
  the *timing* of ADR-0005's non-blocking guarantee; every other property
  of ADR-0005 (wildcards, isolation, per-owner detach, in-process scope)
  stands unchanged.
