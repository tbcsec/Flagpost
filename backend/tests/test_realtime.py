"""WebSocket room lifecycle (Phase 7, §4.1): first-frame auth handshake with a
bounded timeout, room authorization, the join snapshot, and the live
challenge.solved → scoreboard broadcast path end to end."""

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
