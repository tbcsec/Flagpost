"""Scheduled announcements (#349): a future ``publish_at`` holds a post as a
staff-only draft until the scheduler releases it — at which point it broadcasts
and notifies exactly like an immediate one. Editable/cancellable until it fires.

The invariants under test: a draft is invisible to competitors and unbroadcast
until due; the scheduler tick flips it live and emits the *same*
``announcement.published`` (so delivery is identical); edit/cancel work only
while still scheduled; and a past/None ``publish_at`` posts immediately.
"""

from datetime import timedelta

from sqlalchemy import select

from db import SessionLocal, utcnow
from models.audit_log import AuditLogEntry
from tests.conftest import admin_token
from utils.automation_scheduler import publish_scheduled_announcements
from utils.event_bus import event_bus


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def _competition(client) -> str:
    admin = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={"name": "CTF", "participation_mode": "team", "visibility": "public"},
        headers=_auth(admin),
    )
    return resp.json()["id"]


async def _participant(client, comp: str, email: str) -> str:
    """A competitor with challenge_view (via team membership) but not staff."""
    token = await _register(client, email)
    await client.post(
        f"/api/competitions/{comp}/teams",
        json={"name": f"Team {email}"},
        headers=_auth(token),
    )
    return token


async def _feed(client, comp: str, token: str) -> list[dict]:
    return (
        await client.get(f"/api/competitions/{comp}/announcements", headers=_auth(token))
    ).json()


async def _scheduled(client, comp: str, token: str):
    return await client.get(
        f"/api/competitions/{comp}/announcements/scheduled", headers=_auth(token)
    )


async def _post(client, comp: str, token: str, **body):
    return await client.post(
        f"/api/competitions/{comp}/announcements", json=body, headers=_auth(token)
    )


async def _published_audit_count(title: str) -> int:
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "announcement.published"
                )
            )
        ).scalars().all()
    return sum(1 for r in rows if (r.payload or {}).get("title") == title)


# --- scheduling ---------------------------------------------------------------


async def test_scheduled_draft_is_hidden_and_unbroadcast_until_due(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    viewer = await _participant(client, comp, "viewer@example.com")
    future = (utcnow() + timedelta(hours=1)).isoformat()

    resp = await _post(client, comp, admin, title="Later", body="soon", publish_at=future)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["hidden"] is True and data["publish_at"] is not None

    # Invisible on the published feed — to competitors AND staff (it isn't live).
    assert all(a["title"] != "Later" for a in await _feed(client, comp, viewer))
    assert all(a["title"] != "Later" for a in await _feed(client, comp, admin))
    # But present in the staff management list.
    sched = (await _scheduled(client, comp, admin)).json()
    assert [a["title"] for a in sched] == ["Later"]
    # Nothing was broadcast/emitted yet.
    await event_bus.wait_for_background()
    assert await _published_audit_count("Later") == 0


async def test_scheduler_releases_a_due_announcement_like_an_immediate_post(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    viewer = await _participant(client, comp, "viewer@example.com")
    due = utcnow() + timedelta(minutes=30)

    await _post(client, comp, admin, title="Go", body="live", publish_at=due.isoformat())

    # A tick before it's due leaves it hidden.
    await publish_scheduled_announcements(SessionLocal, now=due - timedelta(minutes=1))
    assert all(a["title"] != "Go" for a in await _feed(client, comp, viewer))

    # A tick after it's due publishes it: competitor now sees it, it leaves the
    # scheduled list, and it fired announcement.published exactly once.
    await publish_scheduled_announcements(SessionLocal, now=due + timedelta(seconds=1))
    await event_bus.wait_for_background()
    assert any(a["title"] == "Go" for a in await _feed(client, comp, viewer))
    assert (await _scheduled(client, comp, admin)).json() == []
    assert await _published_audit_count("Go") == 1

    # Idempotent: a later tick doesn't re-fire it.
    await publish_scheduled_announcements(SessionLocal, now=due + timedelta(hours=2))
    await event_bus.wait_for_background()
    assert await _published_audit_count("Go") == 1


async def test_past_publish_at_posts_immediately(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    viewer = await _participant(client, comp, "viewer@example.com")
    past = (utcnow() - timedelta(minutes=5)).isoformat()

    data = (await _post(client, comp, admin, title="Now", body="x", publish_at=past)).json()
    # A past time is immediate: not hidden, no lingering schedule.
    assert data["hidden"] is False and data["publish_at"] is None
    assert any(a["title"] == "Now" for a in await _feed(client, comp, viewer))


# --- edit / cancel ------------------------------------------------------------


async def test_edit_keeps_it_scheduled_then_reschedule_to_now_publishes(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    viewer = await _participant(client, comp, "viewer@example.com")
    future = (utcnow() + timedelta(hours=2)).isoformat()
    aid = (await _post(client, comp, admin, title="Draft", body="v1", publish_at=future)).json()["id"]

    # Edit the body — still a hidden draft, competitor still can't see it.
    r = await client.patch(
        f"/api/competitions/{comp}/announcements/{aid}",
        json={"body": "v2"},
        headers=_auth(admin),
    )
    assert r.status_code == 200 and r.json()["hidden"] is True
    assert all(a["title"] != "Draft" for a in await _feed(client, comp, viewer))

    # Clear the schedule (publish_at: null) → publishes now.
    r = await client.patch(
        f"/api/competitions/{comp}/announcements/{aid}",
        json={"publish_at": None},
        headers=_auth(admin),
    )
    assert r.status_code == 200 and r.json()["hidden"] is False
    await event_bus.wait_for_background()
    feed = await _feed(client, comp, viewer)
    assert any(a["title"] == "Draft" and a["body"] == "v2" for a in feed)


async def test_edit_cannot_retarget_the_audience(client):
    # Audience fields are coupled and type-specific: PATCH edits content/timing
    # only, so a stray audience_type can't desync the row into one that delivers
    # to nobody. The audience stays exactly as posted.
    comp = await _competition(client)
    admin = await admin_token(client)
    future = (utcnow() + timedelta(hours=1)).isoformat()
    aid = (await _post(client, comp, admin, title="A", body="v1", publish_at=future)).json()["id"]

    r = await client.patch(
        f"/api/competitions/{comp}/announcements/{aid}",
        json={"body": "v2", "audience_type": "teams", "audience_ids": ["team-x"]},
        headers=_auth(admin),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["body"] == "v2"  # content edit applied
    assert data["audience_type"] == "all" and data["audience_ids"] == []  # audience untouched


async def test_cancel_a_scheduled_announcement(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    viewer = await _participant(client, comp, "viewer@example.com")
    future = (utcnow() + timedelta(hours=1)).isoformat()
    aid = (await _post(client, comp, admin, title="Oops", body="x", publish_at=future)).json()["id"]

    r = await client.delete(
        f"/api/competitions/{comp}/announcements/{aid}", headers=_auth(admin)
    )
    assert r.status_code == 204
    assert (await _scheduled(client, comp, admin)).json() == []
    # It never reaches the scheduler now, and never reached a competitor.
    await publish_scheduled_announcements(
        SessionLocal, now=utcnow() + timedelta(hours=2)
    )
    await event_bus.wait_for_background()
    assert all(a["title"] != "Oops" for a in await _feed(client, comp, viewer))


async def test_edit_and_cancel_reject_an_already_published_announcement(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    aid = (await _post(client, comp, admin, title="Live", body="x")).json()["id"]  # immediate

    patch = await client.patch(
        f"/api/competitions/{comp}/announcements/{aid}",
        json={"body": "y"},
        headers=_auth(admin),
    )
    assert patch.status_code == 409
    delete = await client.delete(
        f"/api/competitions/{comp}/announcements/{aid}", headers=_auth(admin)
    )
    assert delete.status_code == 409


async def test_scheduling_management_is_staff_only(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    viewer = await _participant(client, comp, "viewer@example.com")
    future = (utcnow() + timedelta(hours=1)).isoformat()
    aid = (await _post(client, comp, admin, title="S", body="x", publish_at=future)).json()["id"]

    assert (await _scheduled(client, comp, viewer)).status_code == 403
    assert (
        await client.patch(
            f"/api/competitions/{comp}/announcements/{aid}",
            json={"body": "z"},
            headers=_auth(viewer),
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"/api/competitions/{comp}/announcements/{aid}", headers=_auth(viewer)
        )
    ).status_code == 403
