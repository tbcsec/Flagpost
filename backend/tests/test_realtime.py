"""WebSocket room lifecycle (Phase 7, §4.1): first-frame auth handshake with a
bounded timeout, room authorization, the join snapshot, and the live
challenge.solved → scoreboard broadcast path end to end."""

import pytest

from config import settings
from tests.conftest import admin_token
from tests.ws_client import WsTestClient


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


async def _joined_participant(client, comp: str, email: str, team: str) -> str:
    token = await _register(client, email)
    resp = await client.post(
        f"/api/competitions/{comp}/teams",
        json={"name": team},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return token


import main  # noqa: E402  (app import mirrors conftest's client fixture)


async def test_scoreboard_room_handshake_snapshot_and_live_update(client):
    comp, chal = await _competition_with_challenge(client)
    token = await _joined_participant(client, comp, "live@example.com", "Livewires")

    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"

        # Join snapshot: current board, team present with zero points.
        snapshot = await ws.receive_json()
        assert snapshot["type"] == "scoreboard"
        assert snapshot["mode"] == "team"
        assert [e["name"] for e in snapshot["entries"]] == ["Livewires"]
        assert snapshot["entries"][0]["points"] == 0

        # A correct solve broadcasts a fresh board to the room.
        resp = await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/submit",
            json={"flag": "flag{win}"},
            headers=_auth(token),
        )
        assert resp.json()["correct"] is True

        update = await ws.receive_json()
        assert update["type"] == "scoreboard"
        assert update["entries"][0] == {
            "rank": 1,
            "subject_id": update["entries"][0]["subject_id"],
            "name": "Livewires",
            "points": 100,
            "last_solve_at": update["entries"][0]["last_solve_at"],
            "bracket": None,
        }
        assert update["entries"][0]["last_solve_at"] is not None


async def test_room_rejects_bad_token(client):
    comp, _ = await _competition_with_challenge(client)
    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": "not-a-jwt"})
        assert await ws.expect_close() == 4401


async def test_room_rejects_missing_token_frame(client):
    comp, _ = await _competition_with_challenge(client)
    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"hello": "no token here"})
        assert await ws.expect_close() == 4401


async def test_room_auth_times_out(client, monkeypatch):
    monkeypatch.setattr(settings, "ws_auth_timeout_seconds", 0.05)
    comp, _ = await _competition_with_challenge(client)
    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        # Send nothing: the server must hang up, not wait forever (§4.1).
        assert await ws.expect_close() == 4401


async def test_room_requires_competition_access(client):
    comp, _ = await _competition_with_challenge(client)
    outsider = await _register(client, "outsider@example.com")  # no role
    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": outsider})
        assert await ws.expect_close() == 4403


async def test_unknown_room_type_is_rejected(client):
    async with WsTestClient(main.app, "/ws/nonsense/whatever") as ws:
        assert await ws.expect_close() == 4404


async def test_banned_user_cannot_open_a_socket(client):
    """A soft-banned account's still-valid access token must be rejected on the
    WS handshake too, not just on REST — otherwise a ban leaks live rooms until
    the short access token expires."""
    comp, _ = await _competition_with_challenge(client)
    admin = await admin_token(client)
    # A real participant on the competition (would normally be allowed in).
    victim = await _register(client, "victim@example.com")
    await client.post(f"/api/competitions/{comp}/teams", json={"name": "V"}, headers=_auth(victim))
    victim_id = (await client.get("/api/auth/me", headers=_auth(victim))).json()["id"]
    # Ban them — their access token stays cryptographically valid for now.
    resp = await client.post(f"/api/users/{victim_id}/ban", headers=_auth(admin))
    assert resp.status_code == 200, resp.text
    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": victim})
        assert await ws.expect_close() == 4401


async def test_challenge_presence_join_and_debounced_clear(client, monkeypatch):
    # Short grace so the end-to-end debounced clear resolves inside the test
    # rather than the 5s default (§4.1); the timing itself is unit-tested.
    monkeypatch.setattr(settings, "ws_presence_grace_seconds", 0.05)
    comp, chal = await _competition_with_challenge(client)
    p1 = await _joined_participant(client, comp, "viewer1@example.com", "One")
    p2 = await _joined_participant(client, comp, "viewer2@example.com", "Two")

    async with WsTestClient(main.app, f"/ws/challenge/{chal}") as ws1:
        await ws1.send_json({"token": p1, "mode": "view"})
        assert (await ws1.receive_json())["type"] == "auth_ok"

        # First presence frame: just this viewer, minimal §4.1 payload shape.
        first = await ws1.receive_json()
        assert first["type"] == "presence"
        assert len(first["members"]) == 1
        assert set(first["members"][0]) == {"id", "name", "role", "mode"}
        assert first["members"][0]["role"] == "participant"
        assert first["members"][0]["mode"] == "view"
        p1_id = first["members"][0]["id"]

        async with WsTestClient(main.app, f"/ws/challenge/{chal}") as ws2:
            await ws2.send_json({"token": p2})
            assert (await ws2.receive_json())["type"] == "auth_ok"
            # Second viewer sees both; the first viewer's set grows to two live.
            assert len((await ws2.receive_json())["members"]) == 2
            grown = await ws1.receive_json()
            assert grown["type"] == "presence"
            assert len(grown["members"]) == 2

        # Second viewer gone → after the grace window the room clears back to one.
        cleared = await ws1.receive_json()
        assert cleared["type"] == "presence"
        assert [m["id"] for m in cleared["members"]] == [p1_id]


async def test_challenge_presence_requires_competition_access(client):
    comp, chal = await _competition_with_challenge(client)
    outsider = await _register(client, "nosy@example.com")  # no role in comp
    async with WsTestClient(main.app, f"/ws/challenge/{chal}") as ws:
        await ws.send_json({"token": outsider})
        assert await ws.expect_close() == 4403


async def test_ticket_presence_reports_staff_role(client):
    comp, chal = await _competition_with_challenge(client)
    admin = await admin_token(client)
    opener = await _joined_participant(client, comp, "stuck@example.com", "Stuck")
    ticket = (
        await client.post(
            f"/api/competitions/{comp}/tickets",
            json={"subject": "Help", "body": "I'm stuck", "challenge_id": chal},
            headers=_auth(opener),
        )
    ).json()["id"]

    async with WsTestClient(main.app, f"/ws/ticket/{ticket}") as ws:
        await ws.send_json({"token": admin})  # staff joins the thread
        assert (await ws.receive_json())["type"] == "auth_ok"
        presence = await ws.receive_json()
        assert presence["type"] == "presence"
        assert presence["members"][0]["role"] == "staff"


async def test_keepalive_ping_gets_a_pong_on_a_broadcast_only_room(client):
    """ADR-0031: the client's app-level keepalive is answered by the endpoint
    itself, and other client frames on a broadcast-only room stay drained."""
    comp, _ = await _competition_with_challenge(client)
    token = await _joined_participant(client, comp, "pinger@example.com", "Pingers")

    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"
        assert (await ws.receive_json())["type"] == "scoreboard"  # join snapshot

        # Junk frames (including an oversized one, which skips the parse) are
        # drained without killing the socket...
        await ws.send_json({"noise": "ignored"})
        await ws.send_json({"filler": "x" * 2048})
        # ...so the ping that follows still gets its pong, in order.
        await ws.send_json({"type": "ping"})
        assert (await ws.receive_json())["type"] == "pong"

        # And the connection is still live: pings keep working.
        await ws.send_json({"type": "ping"})
        assert (await ws.receive_json())["type"] == "pong"


@pytest.mark.competition_lifecycle
async def test_scoreboard_room_rejects_competitor_before_start(client):
    """GHSA-r7j2: the #221 gate — REST 403s a not_started board for competitors,
    so the WS scoreboard room must reject them too (staff exempt)."""
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "Pre", "participation_mode": "team", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]
    token = await _joined_participant(client, comp, "early@example.com", "Early")

    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": token})
        assert await ws.expect_close() == 4403

    # Staff can still watch the board before it opens.
    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": admin})
        assert (await ws.receive_json())["type"] == "auth_ok"


async def test_challenge_presence_room_hides_draft_from_competitors(client):
    """GHSA-r7j2: a draft challenge 404s on REST for competitors, so its presence
    room must reject them rather than confirm the hidden challenge exists."""
    comp, published = await _competition_with_challenge(client)
    admin = await admin_token(client)
    draft = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Secret", "points": 100, "flag": "flag{d}"},
            headers=_auth(admin),
        )
    ).json()["id"]
    token = await _joined_participant(client, comp, "peek@example.com", "Peek")

    async with WsTestClient(main.app, f"/ws/challenge/{draft}") as ws:
        await ws.send_json({"token": token})
        assert await ws.expect_close() == 4403

    # The published challenge's presence room accepts the competitor.
    async with WsTestClient(main.app, f"/ws/challenge/{published}") as ws:
        await ws.send_json({"token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"
