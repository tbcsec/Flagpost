"""Announcements (Phase 8, ROADMAP #14): create RBAC, competition scoping,
ordering, the announcement.published event, and the live WebSocket broadcast +
join snapshot over the §4.1 room."""

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from tests.conftest import admin_token
from tests.ws_client import WsTestClient

import main  # noqa: E402


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": email.split("@")[0],
        },
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


async def test_admin_posts_and_everyone_lists_newest_first(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    viewer = await _participant(client, comp, "viewer@example.com")

    for title in ("First", "Second"):
        resp = await client.post(
            f"/api/competitions/{comp}/announcements",
            json={"title": title, "body": f"{title} body"},
            headers=_auth(admin),
        )
        assert resp.status_code == 201, resp.text

    listing = await client.get(
        f"/api/competitions/{comp}/announcements", headers=_auth(viewer)
    )
    assert [a["title"] for a in listing.json()] == ["Second", "First"]

    async with SessionLocal() as session:
        published = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "announcement.published"
                )
            )
        ).scalars().all()
    assert len(published) == 2


async def test_posting_requires_announcement_create(client):
    comp = await _competition(client)
    participant = await _participant(client, comp, "nostaff@example.com")
    resp = await client.post(
        f"/api/competitions/{comp}/announcements",
        json={"title": "Nope", "body": "no perm"},
        headers=_auth(participant),
    )
    assert resp.status_code == 403


async def test_listing_requires_competition_access(client):
    comp = await _competition(client)
    outsider = await _register(client, "outsider@example.com")  # no role
    resp = await client.get(
        f"/api/competitions/{comp}/announcements", headers=_auth(outsider)
    )
    assert resp.status_code == 403


async def test_announcements_are_scoped_to_their_competition(client):
    admin = await admin_token(client)
    comp_a = await _competition(client)
    comp_b = await _competition(client)
    await client.post(
        f"/api/competitions/{comp_a}/announcements",
        json={"title": "A-only", "body": "x"},
        headers=_auth(admin),
    )
    listing_b = await client.get(
        f"/api/competitions/{comp_b}/announcements", headers=_auth(admin)
    )
    assert listing_b.json() == []


async def test_room_snapshot_and_live_broadcast(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    viewer = await _participant(client, comp, "live@example.com")

    # A pre-existing announcement should arrive in the join snapshot.
    await client.post(
        f"/api/competitions/{comp}/announcements",
        json={"title": "Earlier", "body": "before connect"},
        headers=_auth(admin),
    )

    async with WsTestClient(main.app, f"/ws/announcements/{comp}") as ws:
        await ws.send_json({"token": viewer})
        assert (await ws.receive_json())["type"] == "auth_ok"

        snapshot = await ws.receive_json()
        assert snapshot["type"] == "announcements"
        assert [a["title"] for a in snapshot["announcements"]] == ["Earlier"]

        # A new post is pushed live to the room.
        await client.post(
            f"/api/competitions/{comp}/announcements",
            json={"title": "Live", "body": "pushed"},
            headers=_auth(admin),
        )
        frame = await ws.receive_json()
        assert frame["type"] == "announcement"
        assert frame["announcement"]["title"] == "Live"
        assert frame["announcement"]["body"] == "pushed"
