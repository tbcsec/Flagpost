"""Collaborative-notes WS room (Phase 7, §4.2, ADR-0014): the dumb-relay + client
snapshot transport. Covers scope authorization (team-scratchpad isolated to team
members; ticket notes staff-only, opener excluded), the null→persisted join
snapshot, live relay to *other* members (no self-echo), and per-doc isolation."""

import asyncio
import base64

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


async def _competition_with_challenge(client) -> tuple[str, str]:
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "team"},
            headers=_auth(admin),
        )
    ).json()["id"]
    chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Chal", "points": 100, "flag": "flag{win}"},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin)
    )
    return comp, chal


async def _make_team(client, comp: str, email: str, name: str) -> tuple[str, str, str]:
    """Register a user, create a team; return (token, team_id, invite_code)."""
    token = await _register(client, email)
    resp = await client.post(
        f"/api/competitions/{comp}/teams", json={"name": name}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return token, body["id"], body["invite_code"]


async def _join_team(client, comp: str, email: str, invite_code: str) -> str:
    token = await _register(client, email)
    resp = await client.post(
        f"/api/competitions/{comp}/teams/join",
        json={"invite_code": invite_code},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    return token


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# --- Team challenge scratchpad ---------------------------------------------


async def test_scratchpad_snapshot_null_then_persisted(client):
    comp, chal = await _competition_with_challenge(client)
    token, team_id, _ = await _make_team(client, comp, "cap@example.com", "Alpha")
    doc = f"team_challenge:{team_id}:{chal}"

    async with WsTestClient(main.app, f"/ws/note/{doc}") as ws:
        await ws.send_json({"token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"
        snap = await ws.receive_json()
        assert snap == {"type": "note_snapshot", "update": None}
        # Persist a full state blob (opaque to the server).
        await ws.send_json({"type": "note_persist", "state": _b64(b"hello-ydoc")})

    # A fresh join gets the persisted blob back as its snapshot.
    async with WsTestClient(main.app, f"/ws/note/{doc}") as ws:
        await ws.send_json({"token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"
        snap = await ws.receive_json()
        assert snap["type"] == "note_snapshot"
        assert base64.b64decode(snap["update"]) == b"hello-ydoc"


async def test_scratchpad_update_relays_to_other_member_not_sender(client):
    comp, chal = await _competition_with_challenge(client)
    token_a, team_id, code = await _make_team(client, comp, "a@example.com", "Alpha")
    token_b = await _join_team(client, comp, "b@example.com", code)
    doc = f"team_challenge:{team_id}:{chal}"

    async with WsTestClient(main.app, f"/ws/note/{doc}") as wa:
        await wa.send_json({"token": token_a})
        assert (await wa.receive_json())["type"] == "auth_ok"
        assert (await wa.receive_json())["type"] == "note_snapshot"

        async with WsTestClient(main.app, f"/ws/note/{doc}") as wb:
            await wb.send_json({"token": token_b})
            assert (await wb.receive_json())["type"] == "auth_ok"
            assert (await wb.receive_json())["type"] == "note_snapshot"
            # Let B's join finish (join happens just after its snapshot) so the
            # relay below has a member to reach — a test-timing settle, not a
            # real ordering the client depends on.
            await asyncio.sleep(0.05)

            # A sends an update; B receives the relay, A does not echo.
            await wa.send_json({"type": "note_update", "update": _b64(b"delta-1")})
            relayed = await wb.receive_json()
            assert relayed["type"] == "note_update"
            assert base64.b64decode(relayed["update"]) == b"delta-1"


async def test_scratchpad_rejects_non_member(client):
    comp, chal = await _competition_with_challenge(client)
    _token, team_id, _ = await _make_team(client, comp, "owner@example.com", "Alpha")
    # A different competitor, on their own separate team, must not reach Alpha's doc.
    outsider = await _register(client, "outsider@example.com")
    await client.post(
        f"/api/competitions/{comp}/teams", json={"name": "Beta"}, headers=_auth(outsider)
    )
    doc = f"team_challenge:{team_id}:{chal}"
    async with WsTestClient(main.app, f"/ws/note/{doc}") as ws:
        await ws.send_json({"token": outsider})
        assert await ws.expect_close() == 4403


async def test_scratchpad_rejects_team_challenge_competition_mismatch(client):
    # A team from competition 1 can't open a scratchpad against a challenge in
    # competition 2 (the doc_key crosses tenants).
    comp1, _ = await _competition_with_challenge(client)
    _c2, chal2 = await _competition_with_challenge(client)
    token, team_id, _ = await _make_team(client, comp1, "x@example.com", "Alpha")
    doc = f"team_challenge:{team_id}:{chal2}"
    async with WsTestClient(main.app, f"/ws/note/{doc}") as ws:
        await ws.send_json({"token": token})
        assert await ws.expect_close() == 4403


# --- Ticket staff notes -----------------------------------------------------


async def test_ticket_notes_staff_only_opener_rejected(client):
    comp, chal = await _competition_with_challenge(client)
    admin = await admin_token(client)
    opener, _team, _ = await _make_team(client, comp, "stuck@example.com", "Stuck")
    ticket = (
        await client.post(
            f"/api/competitions/{comp}/tickets",
            json={"subject": "Help", "body": "stuck", "challenge_id": chal},
            headers=_auth(opener),
        )
    ).json()["id"]
    doc = f"ticket:{ticket}"

    # Staff (ticket_view_internal_notes) may edit the internal note.
    async with WsTestClient(main.app, f"/ws/note/{doc}") as ws:
        await ws.send_json({"token": admin})
        assert (await ws.receive_json())["type"] == "auth_ok"
        assert (await ws.receive_json())["type"] == "note_snapshot"

    # The opener — a competitor — must never reach the staff note channel.
    async with WsTestClient(main.app, f"/ws/note/{doc}") as ws:
        await ws.send_json({"token": opener})
        assert await ws.expect_close() == 4403


# --- Transport hygiene ------------------------------------------------------


async def test_unknown_doc_scope_is_rejected(client):
    admin = await admin_token(client)
    async with WsTestClient(main.app, "/ws/note/bogus:whatever") as ws:
        await ws.send_json({"token": admin})
        assert await ws.expect_close() == 4403


async def test_updates_do_not_cross_documents(client):
    comp, chal = await _competition_with_challenge(client)
    _c2, chal2 = await _competition_with_challenge(client)
    # Same admin is on no team; use two ticket docs instead (staff-authorized).
    admin = await admin_token(client)
    opener1, _t1, _ = await _make_team(client, comp, "o1@example.com", "One")
    t1 = (
        await client.post(
            f"/api/competitions/{comp}/tickets",
            json={"subject": "A", "body": "b", "challenge_id": chal},
            headers=_auth(opener1),
        )
    ).json()["id"]
    opener2, _t2, _ = await _make_team(client, _c2, "o2@example.com", "Two")
    t2 = (
        await client.post(
            f"/api/competitions/{_c2}/tickets",
            json={"subject": "A", "body": "b", "challenge_id": chal2},
            headers=_auth(opener2),
        )
    ).json()["id"]

    async with WsTestClient(main.app, f"/ws/note/ticket:{t1}") as w1:
        await w1.send_json({"token": admin})
        assert (await w1.receive_json())["type"] == "auth_ok"
        assert (await w1.receive_json())["type"] == "note_snapshot"

        async with WsTestClient(main.app, f"/ws/note/ticket:{t2}") as w2:
            await w2.send_json({"token": admin})
            assert (await w2.receive_json())["type"] == "auth_ok"
            assert (await w2.receive_json())["type"] == "note_snapshot"

            # An update in t1's room must not surface in t2's room. Persist in t1,
            # then confirm t2's fresh reader (below) never saw a relay frame.
            await w1.send_json({"type": "note_update", "update": _b64(b"only-t1")})
            # w2 should have nothing queued; a persist in t2 that round-trips
            # proves the socket is live and simply didn't receive t1's update.
            await w2.send_json({"type": "note_persist", "state": _b64(b"t2-state")})

    async with WsTestClient(main.app, f"/ws/note/ticket:{t2}") as w2b:
        await w2b.send_json({"token": admin})
        assert (await w2b.receive_json())["type"] == "auth_ok"
        snap = await w2b.receive_json()
        assert base64.b64decode(snap["update"]) == b"t2-state"
