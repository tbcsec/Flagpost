# ADR-0031: Multi-instance deployment behind a load balancer

**Status:** Accepted
**Date:** 2026-08-18
**Architecture reference:** `ARCHITECTURE.md` §4.1 (real-time), §5.2 (scheduler), §13.3 (object storage); extends ADR-0025/0026 from one host to many.

## Context

Organizations want to run Flagpost on managed container platforms — the
motivating ask is AWS ECS/Fargate with an ALB, S3 for object storage, RDS and
ElastiCache — with **N backend tasks** for capacity and rolling deploys.

ADR-0025/0026 built the cross-process realtime layer (Redis pub/sub broadcast
relay, heartbeat-TTL presence) for **multiple workers in one container** and
deliberately scoped the decision to that topology. The mechanisms themselves
are location-agnostic — Redis doesn't care whether subscribers share a kernel —
but four things kept "N containers" from being a supported deployment:

1. **The scheduler assumed one container.** Single-worker runs it in-process;
   multi-worker starts one sidecar per container (`docker-entrypoint.sh`). N
   containers therefore run N schedulers — and job pickup (automation time
   triggers, certificate exports, report renders, retention, update check) has
   no cross-process claim locking, so N schedulers double-fire webhooks and
   render jobs twice.
2. **The relay keyed off local worker count.** `start_realtime()` no-oped when
   `web_concurrency <= 1`, so N single-worker tasks would each conclude they're
   the whole deployment and *silently* stop relaying broadcasts across tasks —
   scoreboards that update only for the lucky fraction of clients on the
   emitting task. The worst kind of failure: invisible.
3. **Idle WebSockets died at the load balancer.** Browsers can't send
   protocol-level pings, the client sent no application-level keepalive, and a
   quiet scoreboard socket has zero traffic — an ALB's default 60s idle timeout
   would cull every idle socket once a minute into pointless reconnect churn.
4. **Object storage required static credentials.** The storage client only
   accepted a key pair, so AWS deployments had to mint and distribute an IAM
   user's long-lived keys instead of using the platform's task roles.

## Decision

Support N app instances sharing Redis/Postgres/object storage, declared by
explicit configuration rather than inferred:

- **`SCHEDULER_ENABLED` (default `true`)** — whether *this* process/container
  may run the singleton scheduler. Multi-instance deployments set it `false` on
  every web task and run **one dedicated `python -m scheduler` service** (the
  existing sidecar module, promoted to its own task). `python -m scheduler`
  itself ignores the flag — running it *is* the opt-in. The web lifespan warns
  loudly when the flag is off, so a deployment that forgot the scheduler
  service sees why time triggers never fire.
- **`MULTI_INSTANCE` (default `false`)** — declares "other processes serve WS
  clients on other hosts." The relay + shared presence now engage when
  `web_concurrency > 1` **or** `multi_instance` is set, and startup fails
  loudly if either is true without `REDIS_URL`. The scheduler service sets it
  too, so its emitted broadcasts relay to web-task clients.
- **Application-level WS keepalive.** The client sends `{"type": "ping"}`
  every 30s on an authed socket; the endpoint answers `{"type": "pong"}`
  centrally, *before* room dispatch, so CRDT room handlers never see it and
  broadcast-only rooms keep draining other frames unparsed (a small size gate
  keeps that path parse-free). Pong frames are swallowed client-side.
- **`MINIO_IAM_AUTH` (default `false`)** — authenticate to S3 with the ECS
  task role / EC2 instance profile via the metadata endpoint (one shared,
  auto-refreshing provider for both storage clients) instead of static keys.
  The static-credential startup guard skips its check in this mode: there are
  no static credentials to leak.
- **Migrations move out of instance startup.** The entrypoint's
  `alembic upgrade head` is correct for one container; N tasks starting
  concurrently race it. Multi-instance deployments run migrations as a one-off
  task (deploy step) and start web tasks with uvicorn directly. This is a
  documented operational pattern, not a code change.

Explicitly rejected: **sticky sessions** (nothing needs them — sockets pin
naturally, sessions live in Postgres, rate limits in Redis) and **inferring
multi-instance** from the environment (a wrong guess here is silent broadcast
loss; topology is the operator's fact to state).

## Consequences

- **Positive:** N tasks behind an ALB with a singleton scheduler service is now
  a declarable, loudly-validated topology. Idle sockets survive default LB
  timers. AWS deployments need no long-lived storage secret. Every default
  preserves existing topologies unchanged (compose single/multi-worker, demo).
- **Accepted degradations (bounded by design):** per-process caches mean up to
  ~5s cross-task scoreboard skew (TTL backstop), N× recomputation of the
  public-insights/activity memos, and per-task activity coalescing (a mass
  solve can produce up to N coalesced pings instead of one). None affect
  correctness.
- **Deferred:** cross-process claim locking (`SKIP LOCKED`) for scheduler jobs
  remains unbuilt — the topology guarantees one scheduler instead. If a future
  HA requirement wants *two* schedulers, that's the follow-up ADR.
- **Verification debt:** ADR-0025/0026's load tests exercised one host. Before
  a real event runs on N tasks, a verification pass is owed: two instances
  behind a load balancer, kill one mid-broadcast, watch relay/presence/
  reconnect/keepalive behave. Until then this topology is *supported but not
  yet load-proven*.
