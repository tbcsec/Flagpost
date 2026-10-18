"""The staff live scoreboard during a freeze (#501).

A ``scoreboard_freeze`` holder sees live standings while competitors see the
frozen board: over REST (``?live=true``) and over the staff-only
``scoreboard_live`` WebSocket room, which carries every movement while the shared
room stays silent. ``live`` on the payload tells the staff view the board is
frozen for competitors even though these standings aren't.
"""

import pytest

from tests.conftest import admin_token
from tests.ws_client import WsTestClient

import main


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, name: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": f"{name}@example.com",
            "password": "password123",
            "display_name": name,
        },
    )
    token = resp.json()["access_token"]
    me = (await client.get("/api/auth/me", headers=_auth(token))).json()
    return token, me["id"]


async def _competition(client, mode: str = "team") -> tuple[str, str]:
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": mode, "visibility": "public"},
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


async def _team_player(client, comp: str, name: str) -> str:
    token, _ = await _register(client, name)
    resp = await client.post(
        f"/api/competitions/{comp}/teams", json={"name": name}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    return token


async def _judge(client, comp: str, name: str) -> tuple[str, str]:
    admin = await admin_token(client)
    token, user_id = await _register(client, name)
    roles = {r["name"]: r for r in (await client.get("/api/roles", headers=_auth(admin))).json()}
    resp = await client.post(
        "/api/roles/assignments",
        json={"user_id": user_id, "role_id": roles["Judge"]["id"], "competition_id": comp},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return token, resp.json()["id"]


async def _solve(client, comp: str, chal: str, token: str) -> None:
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{win}"},
        headers=_auth(token),
    )
    assert resp.json()["correct"] is True


async def _freeze(client, comp: str) -> dict:
    resp = await client.post(
        f"/api/competitions/{comp}/scoreboard/freeze",
        json={},
        headers=_auth(await admin_token(client)),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _joined(ws, token: str, room: str, comp: str) -> dict:
    """Authenticate and return the join snapshot, once the socket is in the room
    (it joins just after the snapshot is sent, so a broadcast fired straight
    away could otherwise find the room empty)."""
    import asyncio

    from realtime import manager

    before = manager.room_size(room, comp)
    await ws.send_json({"token": token})
    assert (await ws.receive_json())["type"] == "auth_ok"
    snapshot = await ws.receive_json()
    assert snapshot["type"] == "scoreboard"
    for _ in range(200):
        if manager.room_size(room, comp) > before:
            break
        await asyncio.sleep(0.01)
    return snapshot


async def _drain_and_expect_silence(ws, timeout: float = 0.3) -> None:
    import asyncio

    from utils.event_bus import event_bus

    await event_bus.wait_for_background()
    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        await ws.next_message(timeout)


def _points(board: dict) -> dict:
    return {e["name"]: e["points"] for e in board["entries"]}


# --- who may join the staff room ---------------------------------------------


async def test_live_room_refuses_competitors_and_outsiders(client):
    comp, _ = await _competition(client)
    player = await _team_player(client, comp, "Player")
    outsider, _ = await _register(client, "outsider")

    for token in (player, outsider):
        async with WsTestClient(main.app, f"/ws/scoreboard_live/{comp}") as ws:
            await ws.send_json({"token": token})
            assert await ws.expect_close() == 4403


async def test_live_room_admits_freeze_holders(client):
    comp, _ = await _competition(client)
    judge, _ = await _judge(client, comp, "judge")
    for token in (await admin_token(client), judge):
        async with WsTestClient(main.app, f"/ws/scoreboard_live/{comp}") as ws:
            snapshot = await _joined(ws, token, "scoreboard_live", comp)
            assert snapshot["frozen"] is False and snapshot["live"] is False


async def test_a_judge_in_another_competition_is_refused(client):
    comp, _ = await _competition(client)
    other, _ = await _competition(client)
    judge, _ = await _judge(client, other, "elsewhere")
    async with WsTestClient(main.app, f"/ws/scoreboard_live/{comp}") as ws:
        await ws.send_json({"token": judge})
        assert await ws.expect_close() == 4403


async def test_losing_the_judge_role_closes_the_live_socket(client):
    comp, _ = await _competition(client)
    judge, assignment = await _judge(client, comp, "demoted")
    async with WsTestClient(main.app, f"/ws/scoreboard_live/{comp}") as ws:
        await _joined(ws, judge, "scoreboard_live", comp)
        resp = await client.delete(
            f"/api/roles/assignments/{assignment}",
            headers=_auth(await admin_token(client)),
        )
        assert resp.status_code == 204, resp.text
        assert await ws.expect_close() is not None
    # And a new handshake is refused.
    async with WsTestClient(main.app, f"/ws/scoreboard_live/{comp}") as ws:
        await ws.send_json({"token": judge})
        assert await ws.expect_close() == 4403


async def _custom_role_holder(client, comp: str, name: str, perms: list[str]) -> str:
    admin = await admin_token(client)
    role = await client.post(
        "/api/roles",
        json={"name": f"{name} role", "scope": "competition", "permissions": perms},
        headers=_auth(admin),
    )
    assert role.status_code == 201, role.text
    token, user_id = await _register(client, name)
    resp = await client.post(
        "/api/roles/assignments",
        json={"user_id": user_id, "role_id": role.json()["id"], "competition_id": comp},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return token


async def test_the_freeze_grant_alone_does_not_open_the_live_room(client):
    """The room keeps the shared room's gates too, as the REST route does."""
    comp, _ = await _competition(client)
    token = await _custom_role_holder(client, comp, "freezeonly", ["scoreboard_freeze"])
    async with WsTestClient(main.app, f"/ws/scoreboard_live/{comp}") as ws:
        await ws.send_json({"token": token})
        assert await ws.expect_close() == 4403


@pytest.mark.competition_lifecycle
async def test_the_live_room_keeps_the_start_gate(client):
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "Pre", "participation_mode": "team", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]
    token = await _custom_role_holder(
        client, comp, "earlybird", ["challenge_view", "scoreboard_freeze"]
    )
    async with WsTestClient(main.app, f"/ws/scoreboard_live/{comp}") as ws:
        await ws.send_json({"token": token})
        assert await ws.expect_close() == 4403
    # Staff who can edit challenges watch before the start, as on the shared room.
    async with WsTestClient(main.app, f"/ws/scoreboard_live/{comp}") as ws:
        await _joined(ws, admin, "scoreboard_live", comp)


# --- what the rooms carry during a freeze ------------------------------------


async def test_staff_follow_live_standings_while_the_shared_room_stays_frozen(client):
    comp, chal = await _competition(client)
    early = await _team_player(client, comp, "Early")
    late = await _team_player(client, comp, "Late")
    await _solve(client, comp, chal, early)
    judge, _ = await _judge(client, comp, "watcher")
    await _freeze(client, comp)

    async with (
        WsTestClient(main.app, f"/ws/scoreboard/{comp}") as public,
        WsTestClient(main.app, f"/ws/scoreboard_live/{comp}") as staff,
    ):
        frozen = await _joined(public, early, "scoreboard", comp)
        assert frozen["frozen"] is True and frozen["live"] is False
        live = await _joined(staff, judge, "scoreboard_live", comp)
        assert live["frozen"] is False and live["live"] is True
        assert _points(live) == {"Early": 100, "Late": 0}

        # A post-cutoff solve: staff see it at once, the shared room stays quiet.
        await _solve(client, comp, chal, late)
        update = await staff.receive_json()
        assert update["live"] is True
        assert _points(update) == {"Early": 100, "Late": 100}
        await _drain_and_expect_silence(public)

        # Unfreezing reaches both rooms with the same, now public, board.
        await client.post(
            f"/api/competitions/{comp}/scoreboard/unfreeze",
            headers=_auth(await admin_token(client)),
        )
        to_staff = await staff.receive_json()
        to_public = await public.receive_json()
        assert to_staff == to_public
        assert to_staff["frozen"] is False and to_staff["live"] is False
        assert _points(to_public) == {"Early": 100, "Late": 100}


async def test_the_freeze_frame_reaches_staff_live(client):
    """The freeze itself moves the shared board, so both rooms get a frame — and
    the staff one must be the live board, marked live, not the frozen one."""
    comp, chal = await _competition(client)
    player = await _team_player(client, comp, "Before")
    await _solve(client, comp, chal, player)
    async with (
        WsTestClient(main.app, f"/ws/scoreboard/{comp}") as public,
        WsTestClient(main.app, f"/ws/scoreboard_live/{comp}") as staff,
    ):
        await _joined(public, player, "scoreboard", comp)
        await _joined(staff, await admin_token(client), "scoreboard_live", comp)
        await _freeze(client, comp)
        to_public = await public.receive_json()
        to_staff = await staff.receive_json()
        assert to_public["frozen"] is True and to_public["live"] is False
        assert to_staff["frozen"] is False and to_staff["live"] is True
        assert _points(to_staff) == {"Before": 100}


async def test_unfrozen_both_rooms_get_the_same_board(client):
    comp, chal = await _competition(client)
    player = await _team_player(client, comp, "Solo")
    async with (
        WsTestClient(main.app, f"/ws/scoreboard/{comp}") as public,
        WsTestClient(main.app, f"/ws/scoreboard_live/{comp}") as staff,
    ):
        await _joined(public, player, "scoreboard", comp)
        await _joined(staff, await admin_token(client), "scoreboard_live", comp)
        await _solve(client, comp, chal, player)
        assert await staff.receive_json() == await public.receive_json()


async def test_live_room_alone_still_gets_frames(client):
    """The broadcast's no-listener shortcut must count the staff room too."""
    comp, chal = await _competition(client)
    player = await _team_player(client, comp, "Alone")
    await _freeze(client, comp)
    async with WsTestClient(main.app, f"/ws/scoreboard_live/{comp}") as staff:
        await _joined(staff, await admin_token(client), "scoreboard_live", comp)
        await _solve(client, comp, chal, player)
        assert _points(await staff.receive_json()) == {"Alone": 100}


async def test_live_frames_reach_other_workers_with_no_local_staff(client, monkeypatch):
    """Multi-worker: room sizes are per worker, so the worker that handles a solve
    may hold no staff socket while a peer does. It must still build and relay
    the live board, or staff on other workers miss it — the unfreeze included."""
    from realtime import manager

    published: list[dict] = []

    class _Relay:
        async def publish(self, payload: dict) -> None:
            published.append(payload)

    comp, chal = await _competition(client)
    player = await _team_player(client, comp, "Elsewhere")
    await _freeze(client, comp)
    from utils.event_bus import event_bus

    await event_bus.wait_for_background()
    monkeypatch.setattr(manager, "_relay", _Relay())
    await _solve(client, comp, chal, player)
    await event_bus.wait_for_background()

    live = [p for p in published if p["room_type"] == "scoreboard_live"]
    assert len(live) == 1
    assert live[0]["message"]["live"] is True
    assert _points(live[0]["message"]) == {"Elsewhere": 100}
    # The shared room still keeps the post-cutoff solve to itself.
    assert not [p for p in published if p["room_type"] == "scoreboard"]


async def test_the_shared_room_does_not_resend_an_unchanged_frozen_board(client):
    """An event that passes the frozen gate but leaves the board as it was sends
    nothing the second time (the room's held digest)."""
    from datetime import timedelta

    from db import ensure_aware_utc
    from models.competition import Competition
    from utils.event_bus import event_bus

    import db as db_module

    comp, _ = await _competition(client)
    player = await _team_player(client, comp, "Steady")
    await _freeze(client, comp)
    async with db_module.SessionLocal() as session:
        frozen_at = ensure_aware_utc(
            (await session.get(Competition, comp)).scoreboard_frozen_at
        )
    before = (frozen_at - timedelta(minutes=1)).isoformat()

    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as public:
        await _joined(public, player, "scoreboard", comp)
        for _ in range(2):
            await event_bus.emit(
                "challenge.solved", {"competition_id": comp, "solved_at": before}
            )
            await event_bus.wait_for_background()
        assert (await public.receive_json())["frozen"] is True
        await _drain_and_expect_silence(public)


# --- REST ---------------------------------------------------------------------


async def test_rest_live_flag_marks_the_staff_view(client):
    comp, chal = await _competition(client)
    player = await _team_player(client, comp, "Rest")
    judge, _ = await _judge(client, comp, "restjudge")

    # Unfrozen: live=true is just the board.
    board = (
        await client.get(f"/api/competitions/{comp}/scoreboard?live=true", headers=_auth(judge))
    ).json()
    assert board["live"] is False and board["frozen"] is False

    await _freeze(client, comp)
    await _solve(client, comp, chal, player)

    staff = (
        await client.get(f"/api/competitions/{comp}/scoreboard?live=true", headers=_auth(judge))
    ).json()
    assert staff["live"] is True and staff["frozen"] is False
    assert _points(staff) == {"Rest": 100}

    # A competitor asking for live gets the frozen board, unmarked.
    theirs = (
        await client.get(f"/api/competitions/{comp}/scoreboard?live=true", headers=_auth(player))
    ).json()
    assert theirs["live"] is False and theirs["frozen"] is True
    assert _points(theirs) == {"Rest": 0}

    # The judge's default read is still the frozen board.
    default = (
        await client.get(f"/api/competitions/{comp}/scoreboard", headers=_auth(judge))
    ).json()
    assert default["frozen"] is True and default["live"] is False


async def test_freeze_and_unfreeze_responses_report_the_freeze(client):
    """The responses are the live board; ``live`` lets the Freeze/Unfreeze
    control show the new state instead of flipping back."""
    comp, _ = await _competition(client)
    frozen = await _freeze(client, comp)
    assert frozen["frozen"] is False and frozen["live"] is True
    unfrozen = (
        await client.post(
            f"/api/competitions/{comp}/scoreboard/unfreeze",
            headers=_auth(await admin_token(client)),
        )
    ).json()
    assert unfrozen["frozen"] is False and unfrozen["live"] is False


async def test_a_scheduled_freeze_is_not_live_until_it_starts(client):
    from datetime import timedelta

    from db import utcnow

    comp, _ = await _competition(client)
    later = (utcnow() + timedelta(hours=1)).isoformat()
    resp = await client.post(
        f"/api/competitions/{comp}/scoreboard/freeze",
        json={"frozen_at": later},
        headers=_auth(await admin_token(client)),
    )
    assert resp.json()["live"] is False and resp.json()["frozen"] is False


# --- the individual-mode roster -----------------------------------------------


async def test_roster_standing_is_live_for_freeze_holders_only(client):
    comp, chal = await _competition(client, mode="individual")
    player, _ = await _register(client, "solver")
    assert (
        await client.post(f"/api/competitions/{comp}/join", headers=_auth(player))
    ).status_code == 200
    judge, _ = await _judge(client, comp, "rosterjudge")
    await _freeze(client, comp)
    await _solve(client, comp, chal, player)

    def row(resp) -> dict:
        (entry,) = [p for p in resp.json() if p["display_name"] == "solver"]
        return entry

    staff = row(await client.get(f"/api/competitions/{comp}/participants", headers=_auth(judge)))
    assert (staff["points"], staff["solve_count"]) == (100, 1)

    theirs = row(
        await client.get(f"/api/competitions/{comp}/participants", headers=_auth(player))
    )
    assert (theirs["points"], theirs["solve_count"]) == (0, 0)
