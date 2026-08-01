"""Update check + anonymous adoption count (#111).

The privacy properties are the point, so they're asserted directly: the request
carries the version and nothing else, and it happens at most once a day per
deployment (which is what makes `requests ≈ deployments` hold without an
identifier).
"""

import json

import pytest
from sqlalchemy import select

from config import settings as app_settings
from db import SessionLocal, utcnow
from datetime import timedelta
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from tests.conftest import admin_token
from utils import update_check
from utils.update_check import (
    is_newer,
    notice_dismissed,
    parse_version,
    run_check,
    update_available,
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def endpoint(monkeypatch):
    """Capture what the check sends, and control what it gets back."""
    calls: list[dict] = []
    state = {"status": 200, "payload": {"latest": "9.9.9"}, "boom": False}

    class _Stream:
        """Stands in for httpx's streaming response context manager."""

        def __init__(self):
            self.status_code = state["status"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_bytes(self):
            payload = state["payload"]
            raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            # Chunked, so the size cap is exercised the way a real stream would
            # hit it rather than in one convenient lump.
            for i in range(0, len(raw), 4096):
                yield raw[i : i + 4096]

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, params=None, headers=None):
            if state["boom"]:
                raise RuntimeError("network down")
            calls.append(
                {"method": method, "url": url, "params": params or {}, "headers": headers or {}}
            )
            return _Stream()

    monkeypatch.setattr(update_check.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(app_settings, "app_version", "1.0.0", raising=False)
    monkeypatch.setattr(app_settings, "demo_mode", False, raising=False)
    monkeypatch.setattr(
        app_settings, "update_check_url", "https://updates.example.com/v1/check",
        raising=False,
    )
    return {"calls": calls, "state": state}


async def _site() -> SiteSettings:
    async with SessionLocal() as session:
        site = await session.get(SiteSettings, SITE_SETTINGS_ID)
        if site is None:
            site = SiteSettings(id=SITE_SETTINGS_ID)
            session.add(site)
            await session.commit()
            await session.refresh(site)
        return site


async def _reload() -> SiteSettings:
    async with SessionLocal() as session:
        return await session.get(SiteSettings, SITE_SETTINGS_ID)


# --- version comparison -----------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.2.3", (1, 2, 3)),
        ("v1.2.3", (1, 2, 3)),
        (" 1.2.3 ", (1, 2, 3)),
        ("1.2.3-rc1", (1, 2, 3)),
        ("dev", None),
        ("", None),
        (None, None),
        ("1.2", None),
        ("not-a-version", None),
        # Anything that could carry markup or a link is refused outright — this
        # value comes off the network and is shown to an administrator.
        ("<script>alert(1)</script>", None),
        ("1.2.3<script>", None),
        ("https://evil.example.com", None),
    ],
)
def test_parse_version(raw, expected):
    assert parse_version(raw) == expected


def test_is_newer():
    assert is_newer("1.2.0", "1.1.9")
    assert is_newer("2.0.0", "1.99.99")
    assert not is_newer("1.1.0", "1.1.0")
    assert not is_newer("1.0.0", "1.1.0")
    # A source build reports "dev" — never tell that operator they're stale.
    assert not is_newer("1.2.0", "dev")
    assert not is_newer("garbage", "1.0.0")


# --- the notice -------------------------------------------------------------


def test_dismissal_is_separate_from_the_fact(monkeypatch):
    """Dismissing silences the banner without making the platform claim it's up
    to date — the settings page reads `update_available`, which is the raw fact,
    and reports the dismissal separately."""
    monkeypatch.setattr(app_settings, "app_version", "1.1.0", raising=False)
    site = SiteSettings(id=SITE_SETTINGS_ID)
    site.latest_known_version = "1.2.0"

    assert update_available(site) is True
    assert notice_dismissed(site) is False

    site.dismissed_update_version = "1.2.0"
    assert notice_dismissed(site) is True
    # The crucial part: still true. Anything else would have the settings page
    # telling an out-of-date admin they're current.
    assert update_available(site) is True

    # A genuinely newer release un-silences it.
    site.latest_known_version = "1.3.0"
    assert notice_dismissed(site) is False
    assert update_available(site) is True


def test_no_notice_when_up_to_date(monkeypatch):
    monkeypatch.setattr(app_settings, "app_version", "1.2.0", raising=False)
    site = SiteSettings(id=SITE_SETTINGS_ID)
    site.latest_known_version = "1.2.0"
    assert update_available(site) is False


# --- what actually goes over the wire ---------------------------------------


async def test_sends_only_the_version(client, endpoint):
    """The privacy contract: one query parameter, and nothing resembling an
    identifier anywhere in the request."""
    await _site()
    await run_check(SessionLocal)

    assert len(endpoint["calls"]) == 1
    call = endpoint["calls"][0]
    assert call["params"] == {"version": "1.0.0"}
    # No cookies, no auth, no install id — the User-Agent carries the version
    # that's already in the query string and nothing else.
    assert set(call["headers"]) == {"User-Agent"}
    assert call["headers"]["User-Agent"] == "Flagpost/1.0.0"


async def test_records_the_result(client, endpoint):
    await _site()
    await run_check(SessionLocal)

    site = await _reload()
    assert site.last_update_check_status == "ok"
    assert site.latest_known_version == "9.9.9"
    assert site.last_update_check_at is not None


async def test_at_most_once_per_day(client, endpoint):
    """The property that makes `requests ≈ deployments` hold. A restart must not
    re-trigger it, which is why the timestamp lives in the database."""
    await _site()
    await run_check(SessionLocal)
    await run_check(SessionLocal)
    await run_check(SessionLocal)
    assert len(endpoint["calls"]) == 1

    # A day later it checks again.
    async with SessionLocal() as session:
        site = await session.get(SiteSettings, SITE_SETTINGS_ID)
        site.last_update_check_at = utcnow() - timedelta(hours=25)
        site.last_update_attempt_at = utcnow() - timedelta(hours=25)
        await session.commit()
    await run_check(SessionLocal)
    assert len(endpoint["calls"]) == 2


async def test_opt_out_is_honoured(client, endpoint):
    async with SessionLocal() as session:
        site = await session.get(SiteSettings, SITE_SETTINGS_ID)
        if site is None:
            site = SiteSettings(id=SITE_SETTINGS_ID)
            session.add(site)
        site.update_checks_enabled = False
        await session.commit()

    await run_check(SessionLocal)
    assert endpoint["calls"] == []


async def test_demo_mode_never_checks(client, endpoint, monkeypatch):
    """The demo resets hourly; letting it check in would report ~24 phantom
    deployments a day and quietly corrupt the metric."""
    monkeypatch.setattr(app_settings, "demo_mode", True, raising=False)
    await _site()
    await run_check(SessionLocal)
    assert endpoint["calls"] == []


async def test_empty_url_disables_it_entirely(client, endpoint, monkeypatch):
    """The air-gapped escape hatch: no call is attempted at all."""
    monkeypatch.setattr(app_settings, "update_check_url", "", raising=False)
    await _site()
    await run_check(SessionLocal)
    assert endpoint["calls"] == []


# --- failure handling -------------------------------------------------------


async def test_network_failure_is_not_an_error(client, endpoint):
    endpoint["state"]["boom"] = True
    await _site()
    await run_check(SessionLocal)  # must not raise

    site = await _reload()
    assert site.last_update_check_status == "unreachable"
    assert site.last_update_check_at is None  # no success recorded


async def test_failure_backs_off_instead_of_hammering(client, endpoint):
    """An endpoint outage must not turn every install into a retry flood."""
    endpoint["state"]["boom"] = True
    await _site()
    await run_check(SessionLocal)
    await run_check(SessionLocal)
    await run_check(SessionLocal)
    # The attempt stamp is written before the request, so a crash mid-call
    # still backs off.
    site = await _reload()
    assert site.last_update_attempt_at is not None


async def test_garbage_version_is_dropped_not_stored(client, endpoint):
    """Untrusted input from the network never reaches an admin's screen."""
    endpoint["state"]["payload"] = {"latest": "<img src=x onerror=alert(1)>"}
    await _site()
    await run_check(SessionLocal)

    site = await _reload()
    assert site.latest_known_version is None
    assert site.last_update_check_status == "error"


async def test_non_json_response_is_handled(client, endpoint):
    endpoint["state"]["payload"] = b"totally not json"
    await _site()
    await run_check(SessionLocal)
    site = await _reload()
    assert site.last_update_check_status == "error"
    assert site.latest_known_version is None


async def test_http_error_is_handled(client, endpoint):
    endpoint["state"]["status"] = 503
    await _site()
    await run_check(SessionLocal)
    site = await _reload()
    assert site.last_update_check_status == "error"


# --- admin surface ----------------------------------------------------------


async def test_settings_expose_status_and_toggle(client):
    admin = await admin_token(client)
    resp = await client.get("/api/site-settings/operational", headers=_auth(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["update_checks_enabled"] is True
    assert "last_update_check_at" in body
    assert "current_version" in body
    assert body["update_available"] is False


async def test_dismiss_pins_to_the_version(client, endpoint):
    admin = await admin_token(client)
    await _site()
    await run_check(SessionLocal)  # latest_known_version = 9.9.9

    resp = await client.post(
        "/api/site-settings/update-notice/dismiss", headers=_auth(admin)
    )
    assert resp.status_code == 200

    site = await _reload()
    assert site.dismissed_update_version == "9.9.9"


async def test_dismiss_requires_permission(client):
    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "nobody", "password": "password123"},
    )
    token = reg.json()["access_token"]
    resp = await client.post(
        "/api/site-settings/update-notice/dismiss", headers=_auth(token)
    )
    assert resp.status_code == 403


async def test_public_settings_never_leak_update_state(client):
    """Competitors have no business knowing the platform is out of date — it's
    an unauthenticated endpoint and a stale-version disclosure."""
    resp = await client.get("/api/site-settings")
    assert resp.status_code == 200
    body = resp.json()
    for leak in (
        "update_checks_enabled",
        "latest_known_version",
        "current_version",
        "update_available",
        "last_update_check_at",
    ):
        assert leak not in body, f"{leak} must not be public"


# --- hostile-response handling ----------------------------------------------


async def test_oversized_response_is_refused(client, endpoint):
    """A compromised endpoint returning an endless body must not be able to
    exhaust every deployment that asks. The body is streamed with a hard cap."""
    endpoint["state"]["payload"] = b'{"latest": "' + b"9" * 200_000 + b'"}'
    await _site()
    await run_check(SessionLocal)

    site = await _reload()
    assert site.last_update_check_status == "error"
    assert site.latest_known_version is None


def test_absurd_version_does_not_reach_int():
    """`\\d+` unbounded would hand int() a 100k-digit string, which CPython
    refuses above 4300 digits — an exception path reachable straight off the
    wire. The digit groups are bounded so it never gets that far."""
    assert parse_version("1.1." + "9" * 100_000) is None
    assert parse_version("1.2.999999999") == (1, 2, 999999999)


async def test_omitted_toggle_does_not_re_enable_checks(client):
    """A settings PUT that doesn't mention update checks must leave them alone.
    This endpoint replaces the whole object, so a default would let a scripted
    client silently opt an install back in to phoning home."""
    admin = await admin_token(client)

    async with SessionLocal() as session:
        site = await session.get(SiteSettings, SITE_SETTINGS_ID)
        if site is None:
            site = SiteSettings(id=SITE_SETTINGS_ID)
            session.add(site)
        site.update_checks_enabled = False
        await session.commit()

    # A plausible partial update — changing registration, saying nothing about
    # update checks.
    resp = await client.put(
        "/api/site-settings/operational",
        json={"registration_open": False},
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["update_checks_enabled"] is False

    site = await _reload()
    assert site.update_checks_enabled is False, "opt-out must survive an unrelated save"


async def test_nothing_goes_out_before_setup_completes(client, endpoint):
    """The wizard offers an opt-out, which is worthless if the first check has
    already fired. The public GET /site-settings creates the settings row (the
    setup page itself calls it), so the guard has to be on setup state, not on
    the row's existence."""
    from models.role import RoleAssignment

    # Strip the fixture's seeded admin, putting the instance back to "needs setup".
    async with SessionLocal() as session:
        for ra in (await session.scalars(select(RoleAssignment))).all():
            await session.delete(ra)
        await session.commit()

    # Simulate the setup page loading: the public endpoint creates the row.
    assert (await client.get("/api/site-settings")).status_code == 200

    await run_check(SessionLocal)
    assert endpoint["calls"] == [], "must not phone home before setup is complete"
