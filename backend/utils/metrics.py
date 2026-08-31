"""Prometheus ``/metrics`` — gated, off by default, operator-scoped (#351).

Kernel-level observability, not a per-competition module: a config gate
(``METRICS_ENABLED`` + a scrape token and/or IP allowlist), an ASGI HTTP-timing
middleware, a ``/metrics`` route mounted in ``main``, and scrape-time collectors
over the WS manager, the event bus, challenge instances, and infra.

Two design rules keep this cheap and safe:

- **prometheus_client is imported lazily** inside :func:`enable`, and every
  ``record_*`` / ``refresh_*`` is a no-op until an operator enables metrics. A
  disabled or zero-infra (SQLite preview / test) stack never loads the package
  and pays nothing.
- **Bounded label cardinality only.** Labels are route *templates* (never raw
  paths with ids), room *types*, instance *states*, event *names* (a fixed
  catalog) — never per-competitor / per-id, which would explode Prometheus.

The endpoint exposes operational cardinality (counts, latencies, pool depth),
never competitor content or PII — see ``PRIVACY.md``.
"""

from __future__ import annotations

import ipaddress
import secrets
import time
from typing import Any

from config import settings

# --- module state (populated by enable()) ------------------------------------

_enabled = False
_registry: Any = None
_http_requests: Any = None
_http_latency: Any = None
_events_total: Any = None
_emit_latency: Any = None
_instances: Any = None
_provision_errors: Any = None
_sched_last_run: Any = None
_sched_last_duration: Any = None


def enabled() -> bool:
    return _enabled


def enable() -> None:
    """Create the registry + instruments (idempotent). Imports prometheus_client
    lazily so a disabled deployment never loads it. Called once at app assembly
    when ``settings.metrics_enabled`` is true."""
    global _enabled, _registry, _http_requests, _http_latency, _events_total
    global _emit_latency, _instances, _provision_errors
    global _sched_last_run, _sched_last_duration
    if _enabled:
        return

    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

    _registry = CollectorRegistry()
    _http_requests = Counter(
        "flagpost_http_requests_total",
        "HTTP requests by method, matched route template, and status class.",
        ["method", "route", "status"],
        registry=_registry,
    )
    _http_latency = Histogram(
        "flagpost_http_request_duration_seconds",
        "HTTP request latency by method and matched route template.",
        ["method", "route"],
        registry=_registry,
    )
    _events_total = Counter(
        "flagpost_events_total",
        "Event-bus emits by event name (the fixed §3.2 catalog).",
        ["event"],
        registry=_registry,
    )
    _emit_latency = Histogram(
        "flagpost_event_emit_duration_seconds",
        "Foreground event dispatch latency (background handlers excluded).",
        registry=_registry,
    )
    _instances = Gauge(
        "flagpost_challenge_instances",
        "Challenge instances by lifecycle state (refreshed on the scheduler tick).",
        ["state"],
        registry=_registry,
    )
    _provision_errors = Counter(
        "flagpost_instance_provision_errors_total",
        "Challenge-instance provisioning failures by reason (exception type).",
        ["reason"],
        registry=_registry,
    )
    _sched_last_run = Gauge(
        "flagpost_scheduler_last_run_timestamp_seconds",
        "Unix time the scheduler last completed a tick (staleness = a dead scheduler).",
        registry=_registry,
    )
    _sched_last_duration = Gauge(
        "flagpost_scheduler_last_tick_duration_seconds",
        "Wall-clock duration of the scheduler's last tick.",
        registry=_registry,
    )
    _registry.register(_RuntimeCollector())
    _enabled = True


# --- record hooks (cheap no-ops when disabled) -------------------------------


def record_http(method: str, route: str, status: int, duration: float) -> None:
    if not _enabled:
        return
    status_class = f"{status // 100}xx"
    _http_requests.labels(method, route, status_class).inc()
    _http_latency.labels(method, route).observe(duration)


def record_event(event_name: str, foreground_duration: float) -> None:
    if not _enabled:
        return
    _events_total.labels(event_name).inc()
    _emit_latency.observe(foreground_duration)


def record_provision_error(reason: str) -> None:
    if not _enabled:
        return
    _provision_errors.labels(reason).inc()


def record_scheduler_tick(duration: float, when: float) -> None:
    if not _enabled:
        return
    _sched_last_duration.set(duration)
    _sched_last_run.set(when)


async def refresh_instance_gauges(db_factory) -> None:
    """Set the per-state instance gauge from a cheap ``COUNT ... GROUP BY status``
    — the only way to get an accurate count across the background provision/reap
    sessions. Called from the scheduler tick, gated so a disabled stack (or one
    without instancing) does no query."""
    if not _enabled:
        return
    from sqlalchemy import func, select

    from models.challenge_instancing import INSTANCE_STATUSES, ChallengeInstance

    async with db_factory() as db:
        rows = (
            await db.execute(
                select(ChallengeInstance.status, func.count()).group_by(
                    ChallengeInstance.status
                )
            )
        ).all()
    counts = {state: 0 for state in INSTANCE_STATUSES}
    for state, n in rows:
        counts[state] = int(n or 0)
    for state, n in counts.items():
        _instances.labels(state).set(n)


# --- scrape-time collector (live gauges read at scrape, not stored) ----------


class _RuntimeCollector:
    """Yields gauges that are cheapest read live at scrape time: WS occupancy,
    the event-bus background-lane depth, relay attachment, and DB pool state.
    Reads the process singletons directly — sync, no I/O, no DB query. Imports
    the singletons lazily to avoid an import cycle (event_bus imports metrics)."""

    def collect(self):
        from prometheus_client.core import GaugeMetricFamily

        # Event-bus background lane depth — the earliest backpressure signal.
        from utils.event_bus import event_bus

        bg = GaugeMetricFamily(
            "flagpost_event_background_inflight",
            "In-flight (incl. nearly-done) background event handlers (ADR-0012).",
        )
        bg.add_metric([], len(event_bus._background_tasks))
        yield bg

        # WebSocket occupancy by room type (§4.1) — the kickoff-spike surface.
        from realtime import manager

        conns = GaugeMetricFamily(
            "flagpost_ws_connections",
            "Live WebSocket sockets by room type.",
            labels=["room_type"],
        )
        rooms = GaugeMetricFamily(
            "flagpost_ws_rooms",
            "Open WebSocket rooms by room type.",
            labels=["room_type"],
        )
        presence = GaugeMetricFamily(
            "flagpost_ws_presence_members",
            "Distinct presence members by room type.",
            labels=["room_type"],
        )
        conn_by_type: dict[str, int] = {}
        room_by_type: dict[str, int] = {}
        pres_by_type: dict[str, int] = {}
        for (room_type, _rid), socks in list(manager._rooms.items()):
            conn_by_type[room_type] = conn_by_type.get(room_type, 0) + len(socks)
            room_by_type[room_type] = room_by_type.get(room_type, 0) + 1
        for (room_type, _rid), members in list(manager._presence.items()):
            pres_by_type[room_type] = pres_by_type.get(room_type, 0) + len(members)
        for room_type, n in conn_by_type.items():
            conns.add_metric([room_type], n)
        for room_type, n in room_by_type.items():
            rooms.add_metric([room_type], n)
        for room_type, n in pres_by_type.items():
            presence.add_metric([room_type], n)
        yield conns
        yield rooms
        yield presence

        relay = GaugeMetricFamily(
            "flagpost_realtime_relay_attached",
            "Whether the cross-worker broadcast relay is attached (1) or not (0).",
        )
        relay.add_metric([], 1.0 if manager._relay is not None else 0.0)
        yield relay

        # DB pool depth (QueuePool on Postgres; SQLite's pool has no such knobs).
        pool = GaugeMetricFamily(
            "flagpost_db_pool_connections",
            "SQLAlchemy connection pool by state.",
            labels=["state"],
        )
        try:
            from db import engine

            db_pool = engine.pool
            pool.add_metric(["in_use"], db_pool.checkedout())
            pool.add_metric(["overflow"], max(0, db_pool.overflow()))
        except Exception:  # noqa: BLE001 — SQLite / older pool: skip pool stats
            pass
        yield pool


# --- scrape gate -------------------------------------------------------------


def scrape_authorized(auth_header: str | None, client: Any) -> bool:
    """True if a scrape may read ``/metrics``. Passes when it satisfies *any*
    configured gate: a matching bearer token (constant-time) OR a client IP in
    the allowlist. The startup guard (config) guarantees at least one is set
    whenever metrics are enabled, so this never falls through to "public"."""
    token = settings.metrics_token
    if token:
        provided = ""
        if auth_header and auth_header.lower().startswith("bearer "):
            provided = auth_header[7:].strip()
        if provided and secrets.compare_digest(provided, token):
            return True

    nets = settings.metrics_allowed_ip_list
    if nets and client is not None:
        # client is a Starlette Address (has .host) or an ASGI (host, port)
        # tuple; guard the empty-tuple edge so indexing can't raise in the gate.
        if isinstance(client, (tuple, list)):
            raw = client[0] if client else None
        else:
            raw = getattr(client, "host", None)
        try:
            ip = ipaddress.ip_address(raw) if raw else None
        except ValueError:
            ip = None
        if ip is not None and any(ip in net for net in nets):
            return True
    return False


def render() -> tuple[bytes, str]:
    """The exposition payload + its content type. Assumes ``enabled()``."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return generate_latest(_registry), CONTENT_TYPE_LATEST


class MetricsMiddleware:
    """Pure-ASGI HTTP timing (the ``BodySizeLimitMiddleware`` pattern). Records
    each request under its *matched route template* — ``scope["route"].path``,
    populated by the Starlette router by the time the app returns — so the label
    set is bounded to real routes (an id in the path never becomes a label).
    Only mounted when metrics are enabled; skips its own ``/metrics`` scrape."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status = 500

        async def wrapped_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        finally:
            route = scope.get("route")
            template = getattr(route, "path", None) or "unmatched"
            record_http(
                scope.get("method", ""),
                template,
                status,
                time.perf_counter() - start,
            )
