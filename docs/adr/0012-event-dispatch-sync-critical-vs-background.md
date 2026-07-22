# ADR-0012: Event dispatch splits into sync-critical vs async-background handlers

**Status:** Accepted
**Date:** 2026-07-22
**Architecture reference:** `ARCHITECTURE.md` §3.1, §15 (resolves the
event-dispatch open question); supersedes ADR-0009; refines ADR-0005

## Context

ADR-0009 recorded that Tier 0's `emit()` awaits every matching handler
(`asyncio.gather`), a deliberate, temporary divergence from §3.1's
"non-blocking emit" property. It was benign while the audit log — a fast local
DB write whose durability we *want* awaited — was the only consumer, and it
explicitly flagged the automation engine's outbound `webhook` action (§5.3) as
the concrete trigger to revisit it.

Tier 3 builds that automation engine (`docs/claude_plans/phase_3.md`), so the
trigger has arrived. A webhook handler makes an external HTTP call that can take
seconds or hang; awaiting it inside `emit()` would hold the mutation's request
open for that whole time (bounded only by the per-handler timeout). §15 left two
candidate models open: (a) split handlers into **sync-critical** vs
**async-background**, or (b) a durable **outbox** for at-least-once async
delivery.

## Decision

Adopt **(a): a sync-critical / async-background split.** A subscription declares
which lane it runs in via a `background` flag; `emit()`:

- runs **foreground** handlers as it does today — awaited together, so the
  triggering request only returns once they've completed (kept as the
  **default**, so existing handlers are unchanged); and
- **schedules** background handlers as fire-and-forget tasks on the event loop
  and returns without awaiting them, so a slow/external handler never holds up
  the response.

Both lanes keep ADR-0005's per-handler isolation and timeout. The audit log and
the in-process WS broadcasts (tickets, scoreboard, notifications) stay
foreground; the automation engine's `webhook` / `send_email` actions (Phase 1–2)
run background.

We deliberately do **not** build a durable outbox now. The split delivers the
property §3.1 actually needs (a slow handler doesn't block the request) with a
few lines of scheduling, whereas an outbox is a table, a worker, and a delivery
state machine — worth it only once at-least-once delivery across a *crash or
restart* is a real requirement. It isn't yet: this is still the single-process
bus of ADR-0005.

## Consequences

- Positive: `emit()` finally honours §3.1's non-blocking guarantee for the
  handlers that need it, while audit durability and deterministic
  "emit-then-assert" tests are preserved for the foreground default. Opting a
  handler into the background lane is a one-flag change, not a rewrite.
- Negative / cost: a background handler's work is **not** guaranteed to have run
  when `emit()` returns, and is **lost on a process crash mid-dispatch** (no
  persistence) — acceptable for a best-effort webhook/notification, not for
  anything that must survive a restart. Tests of background handlers must await
  completion explicitly; the bus exposes `wait_for_background()` for that so the
  suite doesn't race on `asyncio.sleep`.
- Forecloses: nothing permanently. If durable, at-least-once delivery across
  restarts becomes a requirement (or the bus goes multi-process, the ADR-0005
  Redis-pub/sub seam), the **outbox** remains available as an additive layer
  *behind* this same `background` lane — the split and the outbox are
  complementary, not alternatives. This ADR changes only *how background
  handlers are dispatched*; every other ADR-0005 property (wildcards, isolation,
  per-owner detach, in-process scope) stands unchanged.
