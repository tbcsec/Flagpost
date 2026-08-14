"""Competition status lifecycle + manual start/stop (#221).

Covers: the not_started default; the gate on challenges/detail/submit/scoreboard
for competitors (and staff bypass); manual start/stop (permission, transitions,
reversibility, idempotency, events); scheduler auto-transitions with manual
override; and that pause stays orthogonal to status.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from db import SessionLocal, utcnow
from models.audit_log import AuditLogEntry
from models.competition import Competition
from tests.conftest import admin_token

# This module drives the status lifecycle itself, so it opts out of the
# default-running fixture and sees the real production default (not_started).
pytestmark = pytest.mark.competition_lifecycle


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> str:
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return r.json()["access_token"]


async def _competition(client, admin: str, mode: str = "individual") -> str:
    r = await client.post(
        "/api/competitions",
        json={"name": "CTF", "participation_mode": mode, "visibility": "public"},
        headers=_auth(admin),
    )
    return r.json()["id"]


async def _participant(client, comp: str, email: str) -> str:
    token = await _register(client, email)
    r = await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    assert r.status_code == 200, r.text
    return token


async def _published_challenge(client, comp, admin, flag="flag{win}", points=100) -> str:
    r = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "Chal", "points": points, "flag": flag},
        headers=_auth(admin),
    )
    chal = r.json()["id"]
    await client.post(f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin))
    return chal


async def _start(client, comp, admin):
    return await client.post(f"/api/competitions/{comp}/start", headers=_auth(admin))


async def _stop(client, comp, admin):
    return await client.post(f"/api/competitions/{comp}/stop", headers=_auth(admin))


async def _audit_names(comp: str) -> list[str]:
    async with SessionLocal() as db:
        return (
            await db.execute(
                select(AuditLogEntry.event_name).where(AuditLogEntry.competition_id == comp)
            )
        ).scalars().all()


# --- default + schema ------------------------------------------------------


async def test_new_competition_defaults_not_started(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    r = await client.get(f"/api/competitions/{comp}", headers=_auth(admin))
    assert r.status_code == 200 and r.json()["status"] == "not_started"


async def test_status_not_settable_via_patch(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    # A status smuggled into the generic PATCH is ignored (only start/stop move it).
    r = await client.patch(
        f"/api/competitions/{comp}", json={"status": "running"}, headers=_auth(admin)
    )
    assert r.status_code == 200 and r.json()["status"] == "not_started"


# --- gating (not_started) --------------------------------------------------


async def test_not_started_gates_competitor_but_not_staff(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    chal = await _published_challenge(client, comp, admin)
    p = await _participant(client, comp, "np@x.com")
    base = f"/api/competitions/{comp}"

    # Competitor: challenges empty, detail/submit/scoreboard blocked with a message.
    assert (await client.get(f"{base}/challenges", headers=_auth(p))).json() == []
    d = await client.get(f"{base}/challenges/{chal}", headers=_auth(p))
    assert d.status_code == 403 and "hasn't started" in d.json()["detail"]
    s = await client.post(
        f"{base}/challenges/{chal}/submit", json={"flag": "flag{win}"}, headers=_auth(p)
    )
    assert s.status_code == 403 and "hasn't started" in s.json()["detail"]
    sb = await client.get(f"{base}/scoreboard", headers=_auth(p))
    assert sb.status_code == 403 and "hasn't started" in sb.json()["detail"]

    # Staff (admin holds challenge_edit globally) bypass every gate.
    assert len((await client.get(f"{base}/challenges", headers=_auth(admin))).json()) == 1
    assert (await client.get(f"{base}/challenges/{chal}", headers=_auth(admin))).status_code == 200
    assert (await client.get(f"{base}/scoreboard", headers=_auth(admin))).status_code == 200


# --- manual start / stop ---------------------------------------------------


async def test_start_opens_and_stop_closes_the_gate(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    chal = await _published_challenge(client, comp, admin)
    p = await _participant(client, comp, "sc@x.com")
    base = f"/api/competitions/{comp}"

    r = await _start(client, comp, admin)
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert len((await client.get(f"{base}/challenges", headers=_auth(p))).json()) == 1
    assert (await client.get(f"{base}/scoreboard", headers=_auth(p))).status_code == 200
    ok = await client.post(
        f"{base}/challenges/{chal}/submit", json={"flag": "flag{win}"}, headers=_auth(p)
    )
    assert ok.status_code == 200 and ok.json()["correct"] is True

    r = await _stop(client, comp, admin)
    assert r.status_code == 200 and r.json()["status"] == "ended"
    # Challenges close, but the FINAL scoreboard stays visible to competitors.
    assert (await client.get(f"{base}/challenges", headers=_auth(p))).json() == []
    assert (await client.get(f"{base}/scoreboard", headers=_auth(p))).status_code == 200
    ended = await client.get(f"{base}/challenges/{chal}", headers=_auth(p))
    assert ended.status_code == 403 and "has ended" in ended.json()["detail"]


async def test_stop_is_reversible(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _published_challenge(client, comp, admin)
    p = await _participant(client, comp, "rev@x.com")
    base = f"/api/competitions/{comp}"
    await _start(client, comp, admin)
    await _stop(client, comp, admin)
    r = await _start(client, comp, admin)  # re-start an ended competition
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert len((await client.get(f"{base}/challenges", headers=_auth(p))).json()) == 1


async def test_start_stop_are_idempotent(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    assert (await _start(client, comp, admin)).json()["status"] == "running"
    assert (await _start(client, comp, admin)).json()["status"] == "running"  # no error
    assert (await _stop(client, comp, admin)).json()["status"] == "ended"
    assert (await _stop(client, comp, admin)).json()["status"] == "ended"


async def test_competitor_cannot_start_or_stop(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    p = await _participant(client, comp, "perm@x.com")
    assert (await _start(client, comp, p)).status_code == 403
    assert (await _stop(client, comp, p)).status_code == 403


async def test_manual_start_emits_started_event(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _start(client, comp, admin)
    assert "competition.started" in await _audit_names(comp)


async def test_lifecycle_events_fire_once_across_reversible_transitions(client):
    """competition.started / .ended each fire exactly once, so a reversible
    re-start / stop→start→stop never double-runs side-effecting automations."""
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _start(client, comp, admin)
    await _start(client, comp, admin)  # idempotent (already running)
    await _stop(client, comp, admin)
    await _start(client, comp, admin)  # re-open — gate flips, no new event
    await _stop(client, comp, admin)  # re-stop
    names = await _audit_names(comp)
    assert names.count("competition.started") == 1
    assert names.count("competition.ended") == 1


async def test_cancelling_not_started_emits_no_spurious_start(client):
    """Stopping a not-yet-started competition claims the start boundary, so the
    scheduler can't later emit competition.started after the end."""
    from utils.automation_scheduler import emit_lifecycle_events

    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _set_schedule(comp, start=utcnow() - timedelta(minutes=5))  # start reached
    await _stop(client, comp, admin)  # cancel before it ever ran
    await emit_lifecycle_events(SessionLocal)
    names = await _audit_names(comp)
    assert "competition.started" not in names
    async with SessionLocal() as db:
        assert (await db.get(Competition, comp)).status == "ended"


# --- gate coverage: dashboard ticker + post-event feedback -----------------


async def test_recent_solves_ticker_tracks_scoreboard_visibility(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    chal = await _published_challenge(client, comp, admin)
    p = await _participant(client, comp, "tick@x.com")
    base = f"/api/competitions/{comp}"
    solves = f"{base}/dashboard/recent-solves"
    # Not started: closed to the competitor.
    assert (await client.get(solves, headers=_auth(p))).json() == []
    await _start(client, comp, admin)
    await client.post(f"{base}/challenges/{chal}/submit", json={"flag": "flag{win}"}, headers=_auth(p))
    assert len((await client.get(solves, headers=_auth(p))).json()) == 1
    # Ended: the final board is public, so the ticker's solves stay visible too.
    await _stop(client, comp, admin)
    assert len((await client.get(solves, headers=_auth(p))).json()) == 1


async def test_post_event_ratings_not_over_gated(client):
    """The gate lives at the viewing/submission entry points, not the shared
    challenge loader, so post-event feedback (rating a solved challenge) still
    works once the competition has ended."""
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={
                "name": "CTF",
                "participation_mode": "individual",
                "visibility": "public",
                "challenge_ratings_enabled": True,
            },
            headers=_auth(admin),
        )
    ).json()["id"]
    chal = await _published_challenge(client, comp, admin)
    p = await _participant(client, comp, "fb@x.com")
    base = f"/api/competitions/{comp}"
    rate = f"{base}/challenge-ratings/{chal}"
    await _start(client, comp, admin)
    await client.post(f"{base}/challenges/{chal}/submit", json={"flag": "flag{win}"}, headers=_auth(p))
    assert (await client.post(rate, json={"rating": 5}, headers=_auth(p))).status_code == 204
    await _stop(client, comp, admin)
    # Ended, but the solver can still leave/adjust their rating.
    assert (await client.post(rate, json={"rating": 4}, headers=_auth(p))).status_code == 204


# --- scheduler auto-transition + manual override ---------------------------


async def _set_schedule(comp: str, *, start=None, end=None) -> None:
    async with SessionLocal() as db:
        c = await db.get(Competition, comp)
        if start is not None:
            c.start_at = start
        if end is not None:
            c.end_at = end
        await db.commit()


async def test_scheduler_auto_starts_and_ends(client):
    from utils.automation_scheduler import emit_lifecycle_events

    admin = await admin_token(client)
    comp = await _competition(client, admin)
    await _set_schedule(comp, start=utcnow() - timedelta(minutes=5))
    await emit_lifecycle_events(SessionLocal)
    async with SessionLocal() as db:
        assert (await db.get(Competition, comp)).status == "running"

    await _set_schedule(comp, end=utcnow() - timedelta(minutes=1))
    await emit_lifecycle_events(SessionLocal)
    async with SessionLocal() as db:
        assert (await db.get(Competition, comp)).status == "ended"


async def test_manual_stop_not_reopened_by_scheduler(client):
    from utils.automation_scheduler import emit_lifecycle_events

    admin = await admin_token(client)
    comp = await _competition(client, admin)
    # Scheduled to run into the future, but a judge stops early.
    await _set_schedule(
        comp, start=utcnow() - timedelta(minutes=5), end=utcnow() + timedelta(hours=1)
    )
    await _start(client, comp, admin)
    await _stop(client, comp, admin)
    # The scheduler tick must not undo the manual stop (start boundary handled).
    await emit_lifecycle_events(SessionLocal)
    async with SessionLocal() as db:
        assert (await db.get(Competition, comp)).status == "ended"


# --- orthogonality with pause ----------------------------------------------


async def test_pause_is_independent_of_status(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    chal = await _published_challenge(client, comp, admin)
    p = await _participant(client, comp, "pause@x.com")
    base = f"/api/competitions/{comp}"
    await _start(client, comp, admin)
    await client.patch(f"{base}", json={"paused": True}, headers=_auth(admin))
    # Running-but-paused: the board and challenge list are still visible (status
    # gate passes), but submissions are closed by pause (a distinct message).
    assert len((await client.get(f"{base}/challenges", headers=_auth(p))).json()) == 1
    assert (await client.get(f"{base}/scoreboard", headers=_auth(p))).status_code == 200
    s = await client.post(
        f"{base}/challenges/{chal}/submit", json={"flag": "flag{win}"}, headers=_auth(p)
    )
    assert s.status_code == 403 and "paused" in s.json()["detail"]
