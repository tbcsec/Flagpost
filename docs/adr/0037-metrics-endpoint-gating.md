# ADR-0037: Prometheus `/metrics` — kernel middleware, off by default, gated by token/allowlist

**Status:** Accepted
**Date:** 2026-08-31
**Architecture reference:** `ARCHITECTURE.md` §11 (kernel vs modules), §13.4
(outbound calls / observability). Implements #351.

## Context

A self-hosted operator can see *that* a container is up (the health check) but
not *how* it is performing — request latency, WebSocket load, event-bus
background-lane backpressure, live-instance counts, DB-pool depth. During the
hours that matter most (a live event with a hard audience spike at kickoff)
that is the difference between noticing saturation at 40% and finding out when
the scoreboard stops updating. The multi-worker / Fargate+ALB deployment story
(ADR-0025/0026/0031) and the load-testing work (`docs/load-testing/`) make this
gap concrete: the platform is demonstrably stressed exactly where nothing is
observable in production today.

The standard answer is a Prometheus-style `/metrics` endpoint scraped by the
operator's existing monitoring stack. Three decisions needed pinning: **where**
it lives in the architecture, **how** it is secured (a scraper cannot do
interactive JWT), and **whether** it changes the platform's privacy posture.

## Decision

**1. Kernel middleware + a route, not a module.** Metrics is site/deploy-level
with no per-competition meaning, so it is not an optional module (no
`competition_modules` toggle) and not required-core. It is wired in `main.py`
like the `BodySizeLimitMiddleware` and `/api/health` kernel surfaces: an
`utils/metrics` facade, a pure-ASGI HTTP-timing middleware, a `/metrics` route,
and scrape-time collectors over the existing singletons (WS manager, event bus,
DB engine) plus a scheduler-tick refresh for instance-by-state.

**2. Off by default; enabling requires a gate.** `METRICS_ENABLED` defaults
false — inert, matching the AI / instancing "configured before it does anything"
posture, and prometheus_client is imported lazily so a disabled or zero-infra
stack never loads it. `/metrics` exposes internal cardinality (route names,
room/instance counts) so it must **never be public**. It also cannot use the
normal JWT auth (a scraper has no interactive session). Therefore it is gated by
a **static scrape token** (`METRICS_TOKEN`, compared with
`secrets.compare_digest`) **and/or an IP allowlist** (`METRICS_ALLOWED_IPS`),
satisfied by *either* (OR semantics — a trusted-network scraper needs no token;
a token-holder works from anywhere). Enabling with **neither** set is a **hard
startup refusal** (a `Settings` validator, mirroring the multi-worker-Redis
guard) — the one thing we will not do is expose it unauthenticated.

**3. Bounded cardinality; no PII.** Labels are route *templates*
(`scope["route"].path`, never a raw path with ids), room *types*, instance
*states*, and event *names* (the fixed §3.2 catalog) — never per-competitor or
per-id, which would exhaust Prometheus. The endpoint carries operational
signals only (counts, latencies, pool depth), never competitor content. It is an
**inbound pull** surface, so it is *not* a new outbound-call category under
§13.4 — nothing is sent unless a scraper pulls it.

**4. Per-worker registry, documented not solved.** Each worker process keeps its
own in-process registry, so a scrape hits one worker and sees that worker's
numbers. We do not ship a multiprocess aggregator (a shared-dir `prometheus_client`
mode or a sidecar): the default single-worker deployment is exact, and the
multi-worker case is documented — scrape each worker, or accept a single-worker
view. Revisit if a first-class multi-worker exposition becomes necessary.

## Consequences

- An operator's existing Prometheus/Grafana/Alertmanager stack can chart and
  alert on Flagpost with a token and a scrape config; the background-lane
  in-flight gauge and DB-pool depth give the earliest saturation signals.
- Zero cost when disabled (no import, no middleware, no per-request work); a
  cheap no-op behind every `record_*` call otherwise.
- The gate is a deliberately blunt instrument (token / IP), not RBAC — correct
  for a machine scraper, and the startup refusal makes "accidentally public"
  unreachable.
- New optional dependency `prometheus-client` (pure-Python, no infra), pinned
  `>=0.21,<1.0`.
- Multi-worker metrics are per-worker until someone needs otherwise; called out
  here and in `ARCHITECTURE.md` so it is a known limitation, not a surprise.
