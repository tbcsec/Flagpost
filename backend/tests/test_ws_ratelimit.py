"""WebSocket handshake rate limit (#178).

The /ws endpoint was the one authenticated surface with no throttle — an abusive
client could loop reconnects, each forcing a token decode + DB lookup + room
authorize (+ a scoreboard snapshot). The handshake is now rate-limited per
token subject, before that work, closing 4429 once the window is exceeded.
"""

import main
from config import settings
from tests.conftest import admin_token
from tests.ws_client import WsTestClient


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _competition(client, admin: str) -> str:
    return (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _register(client, email: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def test_handshake_rate_limit_closes_4429(client, monkeypatch):
    monkeypatch.setattr(settings, "ws_handshake_rate_limit", 2)
    admin = await admin_token(client)
    comp = await _competition(client, admin)

    # First two handshakes for this subject authenticate fine…
    for _ in range(2):
        async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
            await ws.send_json({"token": admin})
            assert (await ws.receive_json())["type"] == "auth_ok"

    # …the third exceeds the window and is rejected before auth.
    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": admin})
        assert await ws.expect_close() == 4429


async def test_rate_limit_is_per_subject(client, monkeypatch):
    """One user hitting the cap doesn't lock out another (keyed on the sub)."""
    monkeypatch.setattr(settings, "ws_handshake_rate_limit", 1)
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    other = await _register(client, "other@example.com")

    # Admin burns their single allowance.
    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": admin})
        assert (await ws.receive_json())["type"] == "auth_ok"
    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": admin})
        assert await ws.expect_close() == 4429

    # A different subject is unaffected (the participant lacks scoreboard access
    # to this competition, so they're rejected 4403 — auth ran, not throttled).
    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": other})
        assert await ws.expect_close() == 4403
