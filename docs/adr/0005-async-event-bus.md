# ADR-0005: Async pub/sub event bus as the core mutation-notification mechanism

**Status:** Accepted
**Date:** 2026-07-17
**Architecture reference:** `ARCHITECTURE.md` §3

## Context

`VISION.md`'s first core principle is that the platform should
"understand what is happening," not just store data — the audit log,
future automation engine, notifications, analytics, and plugins all need
to react to the same set of mutations (a challenge was solved, a ticket
was created) without each feature reaching into every other feature's
code to know when to fire. The alternative to a shared event mechanism is
each consumer's logic getting called directly from inside the mutation
that triggers it — cheap at first, but it means every new consumer
(automations, a new plugin) requires editing the original mutation code,
and a slow or failing consumer can break the request that triggered it.

## Decision

Build a lightweight async pub/sub event bus as core infrastructure
(kernel-tier, per ADR-0002) at the center of the backend. Core code emits
events (`challenge.solved`, `ticket.assigned`, etc.) and never needs to
know who's listening; consumers (audit log, automation engine,
notifications, plugins) subscribe independently, including via wildcard
patterns (`challenge.*`). Handlers run concurrently, a failure in one is
isolated and logged rather than breaking others or the triggering
request, and emitting an event never blocks the response beyond dispatch.

## Consequences

- Positive: anything that emits an event is automatically automatable —
  the automation engine (§5) is a pure *consumer* of the bus, not a
  parallel system that needs its own wiring per feature.
- Positive: plugins can react to core behavior (§11) without core code
  knowing plugins exist, which is what makes the module system in
  ADR-0002 actually work rather than requiring core code to special-case
  every optional feature.
- Negative / cost: a purely in-process bus (the stated design) doesn't
  survive a process restart or scale past a single backend instance
  without additional work — acceptable for the Docker Compose default
  deployment model, but worth flagging before the Kubernetes/multi
  -instance deployment path (`ARCHITECTURE.md` §2) is taken seriously.
- Negative / cost: because emit doesn't block on slow handlers, a
  handler that never completes (e.g. a hung webhook call) can silently
  never finish rather than surfacing as a request-level error — needs
  handler-level timeouts, not just isolation from other handlers.
- Forecloses: any design where a mutation's side effects are guaranteed
  to have completed by the time the API response returns. That
  guarantee is deliberately traded away for decoupling; anything that
  needs synchronous confirmation (e.g. "did the email definitely send")
  needs its own explicit mechanism, not an assumption riding on event
  dispatch.
