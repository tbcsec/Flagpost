"""Support tickets (Phase 2, ROADMAP #18): create/reply/resolve RBAC, competitor
ownership scoping, internal-note visibility, reopen-on-reply, the §3.2 events,
and the live-thread WS broadcast."""

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

        # Staff replies → the opener's socket gets a ticket_message ping.
        await client.post(
            f"/api/competitions/{comp}/tickets/{tk}/messages",
            json={"body": "on it"},
            headers=_auth(admin),
        )
        frame = await ws.receive_json()
        assert frame["type"] == "ticket_message"
        assert frame["ticket_id"] == tk
