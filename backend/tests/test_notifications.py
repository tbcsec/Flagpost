"""In-app notification center (Tier 3 Phase 0, §4.4): ticket events become
per-user notifications routed like the audio cue, a user sees/mutates only their
own, and new notifications push over the per-user WS room."""

from sqlalchemy import select

from db import SessionLocal
from tests.conftest import admin_token
from tests.ws_client import WsTestClient

import main  # noqa: E402


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def _me_id(client, token) -> str:
    return (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]


async def _competition(client) -> str:
    admin = await admin_token(client)
    return (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _participant(client, comp, email) -> str:
    token = await _register(client, email)
    me = await _me_id(client, token)
    async with SessionLocal() as session:
        from models.role import Role, RoleAssignment

        role = await session.scalar(select(Role).where(Role.name == "Participant"))
        session.add(RoleAssignment(user_id=me, competition_id=comp, role_id=role.id))
        await session.commit()
    return token


async def _open_ticket(client, comp, token, subject="Help", body="stuck") -> str:
    resp = await client.post(
        f"/api/competitions/{comp}/tickets",
        json={"subject": subject, "body": body},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _notifications(client, token) -> list[dict]:
    resp = await client.get("/api/notifications", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- ticket events → notifications, routed like the §4.4 cue ------------------


async def test_ticket_created_notifies_staff_not_opener(client):
    comp = await _competition(client)
    admin = await admin_token(client)  # global Administrator holds ticket_assign
    ada = await _participant(client, comp, "ada@example.com")

    await _open_ticket(client, comp, ada, subject="Invite code broken")

    staff = await _notifications(client, admin)
    assert [n["type"] for n in staff] == ["ticket.created"]
    assert staff[0]["title"] == "New support ticket"
    assert staff[0]["body"] == "Invite code broken"
    assert staff[0]["read"] is False
    assert staff[0]["competition_id"] == comp
    # The opener isn't notified about their own ticket.
    assert await _notifications(client, ada) == []


async def test_staff_reply_notifies_opener_but_internal_note_does_not(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    ticket = await _open_ticket(client, comp, ada)

    # An internal note must not reach the competitor.
    await client.post(
        f"/api/competitions/{comp}/tickets/{ticket}/messages",
        json={"body": "internal only", "is_internal": True},
        headers=_auth(admin),
    )
    assert await _notifications(client, ada) == []

    # A normal staff reply does.
    await client.post(
        f"/api/competitions/{comp}/tickets/{ticket}/messages",
        json={"body": "we're on it"},
        headers=_auth(admin),
    )
    ada_notifs = await _notifications(client, ada)
    assert [n["type"] for n in ada_notifs] == ["ticket.message_posted"]


async def test_participant_reply_notifies_assignee(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    ticket = await _open_ticket(client, comp, ada)

    # Assign to the admin, then have the participant reply.
    await client.post(
        f"/api/competitions/{comp}/tickets/{ticket}/assign",
        json={"assignee_user_id": None},
        headers=_auth(admin),
    )
    admin_before = len(await _notifications(client, admin))
    await client.post(
        f"/api/competitions/{comp}/tickets/{ticket}/messages",
        json={"body": "any update?"},
        headers=_auth(ada),
    )
    admin_after = await _notifications(client, admin)
    # A new ticket.message_posted lands on top of the assign notification.
    assert admin_after[0]["type"] == "ticket.message_posted"
    assert len(admin_after) == admin_before + 1


async def test_resolve_notifies_opener(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    ticket = await _open_ticket(client, comp, ada, subject="RSA hint?")

    await client.post(
        f"/api/competitions/{comp}/tickets/{ticket}/resolve", headers=_auth(admin)
    )
    ada_notifs = await _notifications(client, ada)
    assert ada_notifs[0]["type"] == "ticket.resolved"
    assert ada_notifs[0]["body"] == "RSA hint?"


# --- ownership scoping + read state ------------------------------------------


async def test_only_own_notifications_are_visible_and_mutable(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    await _open_ticket(client, comp, ada)  # notifies admin

    admin_notifs = await _notifications(client, admin)
    assert len(admin_notifs) == 1
    notif_id = admin_notifs[0]["id"]

    # Ada can't see the admin's notification, nor mark it read (404, not 403 —
    # existence isn't disclosed).
    assert await _notifications(client, ada) == []
    resp = await client.post(
        f"/api/notifications/{notif_id}/read", headers=_auth(ada)
    )
    assert resp.status_code == 404


async def test_mark_read_and_unread_count(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    await _open_ticket(client, comp, ada)
    await _open_ticket(client, comp, ada)  # two → admin has two unread

    count = (await client.get("/api/notifications/unread-count", headers=_auth(admin))).json()
    assert count["unread"] == 2

    first = (await _notifications(client, admin))[0]["id"]
    read_resp = await client.post(
        f"/api/notifications/{first}/read", headers=_auth(admin)
    )
    assert read_resp.json()["read"] is True
    count = (await client.get("/api/notifications/unread-count", headers=_auth(admin))).json()
    assert count["unread"] == 1

    await client.post("/api/notifications/read-all", headers=_auth(admin))
    count = (await client.get("/api/notifications/unread-count", headers=_auth(admin))).json()
    assert count["unread"] == 0


# --- per-user preferences (§4.4) ---------------------------------------------


async def test_preferences_default_to_everything_in_app(client):
    token = await admin_token(client)
    prefs = (
        await client.get("/api/notifications/preferences", headers=_auth(token))
    ).json()
    # A fresh user has no stored prefs → resolved defaults: in-app on, sound on,
    # browser off (needs an explicit opt-in + OS grant).
    assert prefs == {
        "inapp_tickets": True,
        "inapp_automations": True,
        "browser": False,
        "sound": True,
    }


async def test_muting_tickets_suppresses_the_in_app_notification(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    # The admin mutes in-app ticket notifications.
    resp = await client.put(
        "/api/notifications/preferences",
        json={
            "inapp_tickets": False,
            "inapp_automations": True,
            "browser": False,
            "sound": True,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 200

    # A new ticket would normally notify staff — now it doesn't reach the admin.
    await _open_ticket(client, comp, ada, subject="muted")
    assert await _notifications(client, admin) == []

    # The preference round-trips.
    prefs = (
        await client.get("/api/notifications/preferences", headers=_auth(admin))
    ).json()
    assert prefs["inapp_tickets"] is False


# --- per-user WS room (§4.4) --------------------------------------------------


async def test_new_notification_pushes_over_user_room(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    admin_id = await _me_id(client, admin)
    ada = await _participant(client, comp, "ada@example.com")

    async with WsTestClient(main.app, f"/ws/user/{admin_id}") as ws:
        await ws.send_json({"token": admin})
        assert (await ws.receive_json())["type"] == "auth_ok"

        # A new ticket notifies staff → the admin's room gets a live frame.
        await _open_ticket(client, comp, ada, subject="live one")
        frame = await ws.receive_json()
        assert frame["type"] == "notification"
        assert frame["notification_type"] == "ticket.created"
        assert frame["title"] == "New support ticket"
        assert frame["read"] is False


async def test_user_room_rejects_other_users(client):
    comp = await _competition(client)
    admin_id = await _me_id(client, await admin_token(client))
    outsider = await _register(client, "outsider@example.com")
    # A user may only join their own room (§4.4).
    async with WsTestClient(main.app, f"/ws/user/{admin_id}") as ws:
        await ws.send_json({"token": outsider})
        assert await ws.expect_close() == 4403
