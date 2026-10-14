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


# --- GHSA-p679: revocation must hold even when a close stalls ---------------


class _HangingWS(_FakeWS):
    """A half-open peer: its close never completes."""

    async def close(self, code: int = 1000) -> None:
        import asyncio

        await asyncio.Event().wait()


async def test_role_updated_is_not_held_up_by_one_stalled_peer(monkeypatch):
    """The old handler closed each holder in turn with no bound on the close,
    so one half-open peer first in line ran it into the bus timeout and every
    later holder kept the pre-edit permissions. Now all are revoked before any
    close is awaited, and closes run concurrently, each bounded."""
    from config import settings

    monkeypatch.setattr(settings, "ws_send_timeout_seconds", 0.05)
    stalled, second, third = _HangingWS(), _FakeWS(), _FakeWS()
    _global_manager.join("note", "ticket:p679a", stalled, "holder-a")
    _global_manager.join("note", "ticket:p679a", second, "holder-b")
    _global_manager.join("note", "ticket:p679a", third, "holder-c")
    try:
        await event_bus.emit(
            "role.updated",
            {"user_id": "admin", "role_id": "r", "name": "Senior Judge",
             "affected_user_ids": ["holder-a", "holder-b", "holder-c"]},
        )
        await event_bus.wait_for_background()

        assert second.closed_code == 4403 and third.closed_code == 4403
        # The stalled one never finished closing, but has no access left.
        assert stalled.closed_code is None
        assert _global_manager.is_revoked(stalled)
    finally:
        for ws in (stalled, second, third):
            _global_manager.leave("note", "ticket:p679a", ws)


async def test_revoked_socket_cannot_keep_acting_when_its_close_stalls(
    client, monkeypatch
):
    """End-to-end, at the router. Simulate a close that never lands (a
    half-open peer, or a revocation relayed from another worker whose close is
    still in flight): the socket must still stop being served — the next frame
    it sends ends the session instead of being handled."""
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]
    token = await _register(client, "stalled@example.com")
    await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    uid = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]

    async def _close_never_lands(targets, code):
        return None

    monkeypatch.setattr(_global_manager, "_close_bounded", _close_never_lands)

    async with WsTestClient(main.app, f"/ws/announcements/{comp}") as ws:
        await ws.send_json({"token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"
        assert (await ws.receive_json())["type"] == "announcements"

        # Served normally before revocation.
        await ws.send_json({"type": "ping"})
        assert (await ws.receive_json())["type"] == "pong"

        banned = await client.post(f"/api/users/{uid}/ban", headers=_auth(admin))
        assert banned.status_code == 200
        await event_bus.wait_for_background()

        # The eviction's close never reached the client — yet its next frame is
        # refused: the session ends with the eviction code instead of a pong.
        await ws.send_json({"type": "ping"})
        message = await ws.next_message()
        assert message["type"] == "websocket.close", message
        assert message.get("code") == 4403


# --- GHSA-p679 review: residual bypasses ------------------------------------


async def _member_socket_setup(client, email: str):
    """A competition member with a live announcements socket. Returns
    (comp_id, token, user_id)."""
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]
    token = await _register(client, email)
    await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    uid = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]
    return comp, token, uid


async def test_a_ghost_socket_is_refused_at_the_router(client):
    """A broadcast send that failed or timed out drops the socket from the
    manager's indexes — and eviction walks those indexes, so it can never find
    the socket again. The reviewer showed a banned user exploiting exactly that
    to keep pushing CRDT updates into teammates' editors. An untracked socket's
    next frame must end the session, not be served."""
    comp, token, uid = await _member_socket_setup(client, "ghost@example.com")

    async with WsTestClient(main.app, f"/ws/announcements/{comp}") as ws:
        await ws.send_json({"token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"
        assert (await ws.receive_json())["type"] == "announcements"

        # A served ping proves the server has joined and is in its receive loop.
        await ws.send_json({"type": "ping"})
        assert (await ws.receive_json())["type"] == "pong"

        # Exactly what the dead-drop path does: leave() — forgotten, not closed.
        (server_ws,) = list(_global_manager._user_sockets[uid])
        _global_manager.leave("announcements", comp, server_ws)

        await ws.send_json({"type": "ping"})
        message = await ws.next_message()
        assert message["type"] == "websocket.close", message  # not a pong


async def test_eviction_landing_mid_handshake_is_not_missed(client, monkeypatch):
    """Between authorize and join the socket isn't indexed yet, so an eviction
    arriving then couldn't mark it — and the socket joined and was served
    indefinitely. The reviewer widened the window by not reading a large
    snapshot. The handshake now snapshots the revocation epoch before it
    authorizes and re-checks it right after joining."""
    import dataclasses

    import importlib

    # `realtime.router` the attribute is the package's exported APIRouter; the
    # module itself has to come from the import system.
    ws_router = importlib.import_module("realtime.router")

    comp, token, uid = await _member_socket_setup(client, "midshake@example.com")

    original = ws_router._room_types["announcements"]

    async def _evicted_during_snapshot(db, user, room_id):
        # The revocation lands while the snapshot is in flight.
        await _global_manager.evict_users([user.id])
        return await original.snapshot(db, user, room_id)

    monkeypatch.setitem(
        ws_router._room_types,
        "announcements",
        dataclasses.replace(original, snapshot=_evicted_during_snapshot),
    )

    async with WsTestClient(main.app, f"/ws/announcements/{comp}") as ws:
        await ws.send_json({"token": token})
        assert (await ws.receive_json())["type"] == "auth_ok"
        assert (await ws.receive_json())["type"] == "announcements"
        # The join-time re-check closes it before it is ever served.
        assert await ws.expect_close() == 4403


async def test_role_update_marks_every_holder_even_if_cut_off(monkeypatch):
    """Pins the eviction.py change itself, not just the bounded close. The old
    handler evicted holders one at a time; with stalled peers first in line it
    ran past the bus timeout and every later holder kept the pre-edit
    permissions. One call marks them all before awaiting anything."""
    import asyncio

    from config import settings
    from realtime.eviction import register_ws_eviction
    from utils.event_bus import EventBus

    monkeypatch.setattr(settings, "ws_send_timeout_seconds", 0.2)
    bus = EventBus(handler_timeout=0.3)  # shorter than two stalled closes
    register_ws_eviction(bus)

    stalled = [_HangingWS() for _ in range(3)]
    last = _FakeWS()
    for i, ws in enumerate(stalled):
        _global_manager.join("note", "ticket:p679c", ws, f"slow-{i}")
    _global_manager.join("note", "ticket:p679c", last, "last-holder")
    try:
        await bus.emit(
            "role.updated",
            {"user_id": "admin", "role_id": "r", "name": "Senior Judge",
             "affected_user_ids": [f"slow-{i}" for i in range(3)] + ["last-holder"]},
        )
        await asyncio.wait_for(bus.wait_for_background(), timeout=10.0)

        assert _global_manager.is_revoked(last)
        assert last.closed_code == 4403
    finally:
        for ws in [*stalled, last]:
            _global_manager.leave("note", "ticket:p679c", ws)
