"""Gated Prometheus /metrics endpoint (#351).

The load-bearing properties: it is inert until enabled, never reachable without a
gate (a startup refusal if enabled with none, a 401 without the credential), its
HTTP labels are bounded to route *templates* (no id explosion), and the
exposition carries the operational instruments — never competitor PII.
"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from config import Settings
from utils import metrics


@pytest.fixture
def metrics_on(monkeypatch):
    """Enable metrics with a known scrape token for the duration of a test, then
    reset the module singleton so it can't leak 'enabled' into other tests."""
    from config import settings

    monkeypatch.setattr(settings, "metrics_token", "scrape-secret-123456")
    monkeypatch.setattr(settings, "metrics_allowed_ips", "")
    metrics._enabled = False  # force a fresh registry
    metrics.enable()
    yield metrics
    metrics._enabled = False


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- config gate --------------------------------------------------------------


def test_enabling_without_a_gate_is_refused_at_startup():
    with pytest.raises(ValidationError, match="never be public"):
        Settings(metrics_enabled=True, metrics_token="", metrics_allowed_ips="")


def test_enabling_with_a_token_or_allowlist_is_accepted():
    assert Settings(metrics_enabled=True, metrics_token="x").metrics_enabled
    assert Settings(
        metrics_enabled=True, metrics_allowed_ips="10.0.0.0/8"
    ).metrics_enabled


def test_allowlist_parses_ips_and_cidrs_dropping_junk():
    s = Settings(metrics_allowed_ips="127.0.0.1, 10.0.0.0/8 , not-an-ip")
    nets = s.metrics_allowed_ip_list
    assert len(nets) == 2  # the junk entry is dropped, not fatal


# --- scrape gate --------------------------------------------------------------


def test_scrape_gate_token(metrics_on, monkeypatch):
    from config import settings

    assert metrics.scrape_authorized(_auth("scrape-secret-123456")["Authorization"], None)
    assert not metrics.scrape_authorized(_auth("wrong")["Authorization"], None)
    assert not metrics.scrape_authorized(None, None)
    # No configured token → the token path never authorizes.
    monkeypatch.setattr(settings, "metrics_token", "")
    assert not metrics.scrape_authorized(_auth("anything")["Authorization"], None)


def test_scrape_gate_ip_allowlist(metrics_on, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "metrics_token", "")
    monkeypatch.setattr(settings, "metrics_allowed_ips", "10.0.0.0/8,127.0.0.1")
    assert metrics.scrape_authorized(None, ("10.4.4.4", 5))  # in CIDR
    assert metrics.scrape_authorized(None, SimpleNamespace(host="127.0.0.1"))
    assert not metrics.scrape_authorized(None, ("8.8.8.8", 5))  # outside
    # Degenerate clients must not crash the gate (they just don't authorize).
    assert not metrics.scrape_authorized(None, ())
    assert not metrics.scrape_authorized(None, SimpleNamespace())


# --- exposition + instruments -------------------------------------------------


def test_exposition_carries_the_core_instruments(metrics_on):
    metrics.record_http("GET", "/api/challenges", 200, 0.01)
    metrics.record_event("challenge.solved", 0.002)
    metrics.record_provision_error("CapReached")
    metrics.record_scheduler_tick(0.5, 1_700_000_000.0)
    body, content_type = metrics.render()
    text = body.decode()
    assert "text/plain" in content_type
    for name in (
        "flagpost_http_requests_total",
        "flagpost_http_request_duration_seconds",
        "flagpost_events_total",
        "flagpost_instance_provision_errors_total",
        "flagpost_scheduler_last_run_timestamp_seconds",
        "flagpost_event_background_inflight",  # from the scrape-time collector
        "flagpost_db_pool_connections",
    ):
        assert name in text, name


async def test_refresh_instance_gauges_runs_and_exposes_states(metrics_on):
    from db import SessionLocal

    await metrics.refresh_instance_gauges(SessionLocal)
    text = metrics.render()[0].decode()
    # Every known state is a bounded label, present even at zero.
    assert 'flagpost_challenge_instances{state="running"}' in text


# --- HTTP middleware records the route TEMPLATE, not the raw path -------------


async def test_http_middleware_uses_route_template_not_raw_path(metrics_on):
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent = []

    async def send(message):
        sent.append(message)

    async def fake_app(scope, receive, send):
        # Starlette populates scope["route"] during routing; emulate it.
        scope["route"] = SimpleNamespace(path="/api/competitions/{competition_id}")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/competitions/abc-123-uuid",  # a real id in the path
        "headers": [],
    }
    await metrics.MetricsMiddleware(fake_app)(scope, receive, send)

    text = metrics.render()[0].decode()
    assert 'route="/api/competitions/{competition_id}"' in text  # template kept
    assert "abc-123-uuid" not in text  # the id never becomes a label
    assert 'status="2xx"' in text


# --- the /metrics route: inert when off, gated when on ------------------------


async def test_metrics_route_is_inert_when_disabled(client):
    # Default fixtures leave metrics off — the endpoint 404s (never public).
    resp = await client.get("/metrics")
    assert resp.status_code == 404


async def test_metrics_route_requires_the_token_when_enabled(client, metrics_on):
    unauthorized = await client.get("/metrics")
    assert unauthorized.status_code == 401

    ok = await client.get("/metrics", headers=_auth("scrape-secret-123456"))
    assert ok.status_code == 200
    assert "flagpost_" in ok.text
