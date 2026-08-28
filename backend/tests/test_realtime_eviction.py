"""Server-driven WebSocket revocation (#10): a ban / account deletion / team
removal drops the socket the user already holds, not just new handshakes."""

import main  # noqa: F401  (registers the eviction listeners at import)
from realtime.manager import ConnectionManager
from tests.conftest import admin_token
from tests.ws_client import WsTestClient
from utils.event_bus import event_bus


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class _FakeWS:
    def __init__(self) -> None:
        self.closed_code: int | None = None

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code


async def test_close_user_sockets_closes_all_of_a_users_sockets():
    mgr = ConnectionManager()
    a1, a2, b1 = _FakeWS(), _FakeWS(), _FakeWS()
    mgr.join("scoreboard", "c1", a1, "alice")
    mgr.join("note", "team_challenge:t1:x", a2, "alice")
    mgr.join("scoreboard", "c1", b1, "bob")

    assert await mgr.close_user_sockets("alice") == 2
    assert a1.closed_code == 4403 and a2.closed_code == 4403
    assert b1.closed_code is None  # a different user is untouched


async def test_close_user_sockets_filters_by_room_and_prefix():
    mgr = ConnectionManager()
    note_t1, note_t2, board = _FakeWS(), _FakeWS(), _FakeWS()
    mgr.join("note", "team_challenge:t1:c", note_t1, "alice")
    mgr.join("note", "team_challenge:t2:c", note_t2, "alice")
    mgr.join("scoreboard", "comp", board, "alice")

    closed = await mgr.close_user_sockets(
        "alice", room_type="note", room_id_prefix="team_challenge:t1:"
    )
    assert closed == 1
    assert note_t1.closed_code == 4403
    assert note_t2.closed_code is None and board.closed_code is None


async def test_leave_clears_the_reverse_index():
    mgr = ConnectionManager()
    ws = _FakeWS()
    mgr.join("scoreboard", "c1", ws, "alice")
    mgr.leave("scoreboard", "c1", ws)
    assert await mgr.close_user_sockets("alice") == 0


async def _register(client, email: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def test_ban_closes_the_users_live_socket(client):
    """End-to-end: an open socket is force-closed when the account is banned."""
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]
    token = await _register(client, "victim@example.com")
    await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    uid = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]

    async with WsTestClient(main.app, f"/ws/announcements/{comp}") as ws:
        await ws.send_json({"token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"
        assert (await ws.receive_json())["type"] == "announcements"  # join snapshot

        banned = await client.post(f"/api/users/{uid}/ban", headers=_auth(admin))
        assert banned.status_code == 200
        await event_bus.wait_for_background()

        assert await ws.expect_close() == 4403


# --- F4: mid-session privilege revocation evicts live sockets ----------------

from realtime.manager import manager as _global_manager  # noqa: E402


async def test_role_unassigned_evicts_the_demoted_user_not_the_actor():
    # F4: unassigning a role mid-session must drop the demoted user's live staff
    # sockets. The demoted user is `subject_user_id`; `user_id` is the acting admin.
    demoted, actor = _FakeWS(), _FakeWS()
    _global_manager.join("note", "ticket:f4a", demoted, "judge-f4")
    _global_manager.join("note", "ticket:f4a", actor, "admin-f4")
    try:
        await event_bus.emit(
            "role.unassigned",
            {"user_id": "admin-f4", "subject_user_id": "judge-f4",
             "role_id": "r", "competition_id": "c"},
        )
        await event_bus.wait_for_background()
        assert demoted.closed_code == 4403      # the demoted judge is evicted
        assert actor.closed_code is None         # the acting admin is untouched
    finally:
        _global_manager.leave("note", "ticket:f4a", demoted)
        _global_manager.leave("note", "ticket:f4a", actor)


async def test_role_updated_evicts_affected_holders_only_on_permission_change():
    # F4: a custom role's permission change re-handshakes its current holders,
    # carried in affected_user_ids. A cosmetic edit (no such key) evicts nobody.
    holder, bystander = _FakeWS(), _FakeWS()
    _global_manager.join("note", "ticket:f4b", holder, "holder-f4")
    _global_manager.join("note", "ticket:f4b", bystander, "other-f4")
    try:
        await event_bus.emit(
            "role.updated",
            {"user_id": "admin-f4", "role_id": "r", "name": "Senior Judge",
             "affected_user_ids": ["holder-f4"]},
        )
        await event_bus.wait_for_background()
        assert holder.closed_code == 4403
        assert bystander.closed_code is None

        # A name-only edit carries no affected_user_ids -> no eviction.
        cosmetic = _FakeWS()
        _global_manager.join("note", "ticket:f4b", cosmetic, "holder-f4")
        await event_bus.emit(
            "role.updated",
            {"user_id": "admin-f4", "role_id": "r", "name": "Renamed"},
        )
        await event_bus.wait_for_background()
        assert cosmetic.closed_code is None
        _global_manager.leave("note", "ticket:f4b", cosmetic)
    finally:
        _global_manager.leave("note", "ticket:f4b", holder)
        _global_manager.leave("note", "ticket:f4b", bystander)
