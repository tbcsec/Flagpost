"""Support tickets (Phase 2, ROADMAP #18): create/reply/resolve RBAC, competitor
ownership scoping, internal-note visibility, reopen-on-reply, the §3.2 events,
and the live-thread WS broadcast."""

import pytest
from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
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


async def _competition(client, mode="individual") -> str:
    admin = await admin_token(client)
    return (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": mode, "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _participant(client, comp, email) -> str:
    """A competitor with ticket_view + ticket_respond via the Participant role."""
    token = await _register(client, email)
    me = (await client.get("/api/auth/me", headers=_auth(token))).json()
    async with SessionLocal() as session:
        from models.role import Role, RoleAssignment

        role = await session.scalar(select(Role).where(Role.name == "Participant"))
        session.add(RoleAssignment(user_id=me["id"], competition_id=comp, role_id=role.id))
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


async def test_create_requires_ticket_respond(client):
    comp = await _competition(client)
    outsider = await _register(client, "nostaff@example.com")  # no role
    resp = await client.post(
        f"/api/competitions/{comp}/tickets",
        json={"subject": "hi", "body": "x"},
        headers=_auth(outsider),
    )
    assert resp.status_code == 403


async def test_competitor_sees_only_own_tickets(client):
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    bob = await _participant(client, comp, "bob@example.com")
    admin = await admin_token(client)

    await _open_ticket(client, comp, ada, "Ada's ticket")
    await _open_ticket(client, comp, bob, "Bob's ticket")

    ada_list = (await client.get(f"/api/competitions/{comp}/tickets", headers=_auth(ada))).json()
    assert [t["subject"] for t in ada_list] == ["Ada's ticket"]
    # Staff see every ticket.
    staff_list = (await client.get(f"/api/competitions/{comp}/tickets", headers=_auth(admin))).json()
    assert {t["subject"] for t in staff_list} == {"Ada's ticket", "Bob's ticket"}


async def test_cannot_read_someone_elses_ticket(client):
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    bob = await _participant(client, comp, "bob@example.com")
    tk = await _open_ticket(client, comp, ada)
    resp = await client.get(f"/api/competitions/{comp}/tickets/{tk}", headers=_auth(bob))
    assert resp.status_code == 404


async def test_create_emits_event_and_has_opening_message(client):
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    resp = await client.post(
        f"/api/competitions/{comp}/tickets",
        json={"subject": "Instance down", "body": "Stack Smash won't spawn"},
        headers=_auth(ada),
    )
    detail = resp.json()
    assert detail["status"] == "open"
    assert len(detail["messages"]) == 1
    assert detail["messages"][0]["body"] == "Stack Smash won't spawn"

    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.event_name == "ticket.created")
            )
        ).scalars().all()
    assert len(events) == 1


async def test_internal_notes_hidden_from_competitor(client):
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    admin = await admin_token(client)
    tk = await _open_ticket(client, comp, ada)

    # Staff posts an internal note + a public reply.
    await client.post(
        f"/api/competitions/{comp}/tickets/{tk}/messages",
        json={"body": "internal: dupe of TICKET-3", "is_internal": True},
        headers=_auth(admin),
    )
    await client.post(
        f"/api/competitions/{comp}/tickets/{tk}/messages",
        json={"body": "We're looking into it.", "is_internal": False},
        headers=_auth(ada),  # (ada's own public reply)
    )

    ada_view = (await client.get(f"/api/competitions/{comp}/tickets/{tk}", headers=_auth(ada))).json()
    bodies = [m["body"] for m in ada_view["messages"]]
    assert "internal: dupe of TICKET-3" not in bodies  # note hidden
    staff_view = (await client.get(f"/api/competitions/{comp}/tickets/{tk}", headers=_auth(admin))).json()
    staff_bodies = [m["body"] for m in staff_view["messages"]]
    assert "internal: dupe of TICKET-3" in staff_bodies


async def test_competitor_cannot_post_internal_note(client):
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    tk = await _open_ticket(client, comp, ada)
    resp = await client.post(
        f"/api/competitions/{comp}/tickets/{tk}/messages",
        json={"body": "sneaky", "is_internal": True},
        headers=_auth(ada),
    )
    assert resp.status_code == 403


async def test_resolve_requires_staff_and_reply_reopens(client):
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    admin = await admin_token(client)
    tk = await _open_ticket(client, comp, ada)

    # Competitor can't resolve.
    assert (
        await client.post(f"/api/competitions/{comp}/tickets/{tk}/resolve", headers=_auth(ada))
    ).status_code == 403

    resolved = await client.post(
        f"/api/competitions/{comp}/tickets/{tk}/resolve", headers=_auth(admin)
    )
    assert resolved.json()["status"] == "resolved"

    # A reply reopens it.
    reopened = await client.post(
        f"/api/competitions/{comp}/tickets/{tk}/messages",
        json={"body": "still broken"},
        headers=_auth(ada),
    )
    assert reopened.json()["status"] == "open"


async def test_competitor_replies_are_throttled_staff_replies_are_not(client, monkeypatch):
    """GHSA-4wrj: a competitor's reply can notify the whole staff queue, so
    replies are rate-limited per user, like opening tickets. Staff replies
    notify only the opener and stay unthrottled."""
    import routers.tickets as tickets_router

    monkeypatch.setattr(tickets_router, "_TICKET_REPLY_LIMIT", 2)
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    admin = await admin_token(client)
    tk = await _open_ticket(client, comp, ada)
    url = f"/api/competitions/{comp}/tickets/{tk}/messages"

    for _ in range(2):
        assert (await client.post(url, json={"body": "more"}, headers=_auth(ada))).status_code == 200
    resp = await client.post(url, json={"body": "again"}, headers=_auth(ada))
    assert resp.status_code == 429
    for _ in range(3):
        assert (await client.post(url, json={"body": "on it"}, headers=_auth(admin))).status_code == 200
    thread = (await client.get(f"/api/competitions/{comp}/tickets/{tk}", headers=_auth(ada))).json()
    assert [m["body"] for m in thread["messages"]].count("again") == 0


async def test_assign_sets_assignee_and_emits(client):
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    admin = await admin_token(client)
    tk = await _open_ticket(client, comp, ada)

    resp = await client.post(
        f"/api/competitions/{comp}/tickets/{tk}/assign", json={}, headers=_auth(admin)
    )
    assert resp.status_code == 200
    assert resp.json()["assignee_name"] == "Administrator"

    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.event_name == "ticket.assigned")
            )
        ).scalars().all()
    assert len(events) == 1


async def test_live_thread_broadcast(client):
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    admin = await admin_token(client)
    tk = await _open_ticket(client, comp, ada)

    async with WsTestClient(main.app, f"/ws/ticket/{tk}") as ws:
        await ws.send_json({"token": ada})
        assert (await ws.receive_json())["type"] == "auth_ok"
        # The ticket room now carries presence (§4.1): the opener's own join
        # frame arrives before any thread activity.
        assert (await ws.receive_json())["type"] == "presence"

        # Staff replies → the opener's socket gets a ticket_message ping.
        await client.post(
            f"/api/competitions/{comp}/tickets/{tk}/messages",
            json={"body": "on it"},
            headers=_auth(admin),
        )
        frame = await ws.receive_json()
        assert frame["type"] == "ticket_message"
        assert frame["ticket_id"] == tk


async def _list(client, comp, token) -> dict:
    rows = (await client.get(f"/api/competitions/{comp}/tickets", headers=_auth(token))).json()
    return {row["id"]: row for row in rows}


async def _post(client, comp, tk, token, body, internal=False):
    resp = await client.post(
        f"/api/competitions/{comp}/tickets/{tk}/messages",
        json={"body": body, "is_internal": internal},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text


async def test_queue_shows_who_is_waiting_and_who_has_it(client):
    """#503: the staff queue's triage signals. A ticket waits on staff while its
    opener spoke last in public; an internal note doesn't answer them."""
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    admin = await admin_token(client)
    admin_id = (await client.get("/api/auth/me", headers=_auth(admin))).json()["id"]
    tk = await _open_ticket(client, comp, ada)

    row = (await _list(client, comp, admin))[tk]
    assert row["awaiting_staff"] is True
    assert row["assignee_user_id"] is None
    opened_at = row["last_activity_at"]
    assert opened_at is not None

    await _post(client, comp, tk, admin, "checking with the author", internal=True)
    row = (await _list(client, comp, admin))[tk]
    assert row["awaiting_staff"] is True  # still unanswered
    assert row["last_activity_at"] > opened_at  # staff see their note's activity
    # The competitor's view doesn't move for a note they can't see.
    assert (await _list(client, comp, ada))[tk]["last_activity_at"] == opened_at

    await _post(client, comp, tk, admin, "Try restarting the instance.")
    assert (await _list(client, comp, admin))[tk]["awaiting_staff"] is False
    await _post(client, comp, tk, ada, "Still broken.")
    assert (await _list(client, comp, admin))[tk]["awaiting_staff"] is True

    await client.post(f"/api/competitions/{comp}/tickets/{tk}/assign", json={}, headers=_auth(admin))
    await client.post(f"/api/competitions/{comp}/tickets/{tk}/resolve", headers=_auth(admin))
    row = (await _list(client, comp, admin))[tk]
    assert row["assignee_user_id"] == admin_id
    assert row["awaiting_staff"] is False  # resolved: nobody's waiting


async def test_message_counts_match_the_thread_each_caller_sees(client):
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    admin = await admin_token(client)
    tk = await _open_ticket(client, comp, ada)
    await _post(client, comp, tk, admin, "internal only", internal=True)
    await _post(client, comp, tk, admin, "public reply")

    assert (await _list(client, comp, ada))[tk]["message_count"] == 2
    assert (await _list(client, comp, admin))[tk]["message_count"] == 3
    detail = (await client.get(f"/api/competitions/{comp}/tickets/{tk}", headers=_auth(ada))).json()
    assert detail["message_count"] == len(detail["messages"]) == 2


async def test_staff_without_internal_notes_count_only_what_they_can_read(client):
    """A desk role can work tickets without reading internal notes: its counts
    leave the notes out too."""
    from models.role import Role, RoleAssignment

    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    admin = await admin_token(client)
    desk = await _register(client, "desk@example.com")
    desk_id = (await client.get("/api/auth/me", headers=_auth(desk))).json()["id"]
    async with SessionLocal() as session:
        role = Role(name="Desk", scope="competition", permissions=["ticket_view", "ticket_respond", "ticket_assign"])
        session.add(role)
        await session.flush()
        session.add(RoleAssignment(user_id=desk_id, competition_id=comp, role_id=role.id))
        await session.commit()
    tk = await _open_ticket(client, comp, ada)
    await _post(client, comp, tk, admin, "internal only", internal=True)

    assert (await _list(client, comp, desk))[tk]["message_count"] == 1
    assert (await _list(client, comp, admin))[tk]["message_count"] == 2


async def _in_room(room_type: str, room_id: str) -> None:
    """A socket joins its room just after authenticating; wait until it has."""
    import asyncio

    from realtime import manager

    for _ in range(200):
        if manager.room_size(room_type, room_id):
            return
        await asyncio.sleep(0.01)


async def _drain_silence(ws, timeout: float = 0.3) -> None:
    import asyncio
    import json

    from utils.event_bus import event_bus

    await event_bus.wait_for_background()
    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        while True:
            raw = await ws.next_message(timeout)
            frame = json.loads(raw.get("text") or "{}")
            # Presence comes and goes on its own; it's not thread activity.
            if frame.get("type") != "presence":
                raise AssertionError(f"unexpected frame {raw}")


async def test_internal_notes_stay_off_the_competitors_socket(client):
    """#503: an internal note — even a body-less ping, and the chime it plays —
    never reaches the competitor's ticket socket. Staff get it through the
    staff-only support room, which refreshes the ticket they have open."""
    from utils.event_bus import event_bus

    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    admin = await admin_token(client)
    tk = await _open_ticket(client, comp, ada)

    async with (
        WsTestClient(main.app, f"/ws/ticket/{tk}") as competitor,
        WsTestClient(main.app, f"/ws/support/{comp}") as staff,
    ):
        await competitor.send_json({"token": ada})
        assert (await competitor.receive_json())["type"] == "auth_ok"
        assert (await competitor.receive_json())["type"] == "presence"
        await staff.send_json({"token": admin})
        assert (await staff.receive_json())["type"] == "auth_ok"
        await _in_room("support", comp)
        await event_bus.wait_for_background()

        await _post(client, comp, tk, admin, "checking with the author", internal=True)
        update = await staff.receive_json()
        assert update == {"type": "ticket_updated", "ticket_id": tk}
        await _drain_silence(competitor)

        # A public reply still reaches them live.
        await _post(client, comp, tk, admin, "on it")
        frame = await competitor.receive_json()
        while frame["type"] == "presence":
            frame = await competitor.receive_json()
        assert frame["type"] == "ticket_message"
