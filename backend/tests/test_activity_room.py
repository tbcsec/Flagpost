"""The per-competition activity room (§4.1, issue #18): authorization, the
curated event → ping fan-out (including the new ``challenge.attempted``), what
deliberately does *not* reach the room, and the thread-reply → support-queue
bump that shipped alongside it."""

import asyncio

import pytest

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
            json={"name": "CTF", "participation_mode": "team", "visibility": "public"},
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


async def _expect_silence(ws: WsTestClient, timeout: float = 0.3) -> None:
    """Assert no frame arrives within ``timeout`` — the room stayed quiet."""
    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        await ws.next_message(timeout)


import main  # noqa: E402  (app import mirrors conftest's client fixture)


async def test_activity_room_admits_members_and_rejects_outsiders(client):
    comp, _ = await _competition_with_challenge(client)
    member = await _joined_participant(client, comp, "member@example.com", "In")
    outsider = await _register(client, "outsider@example.com")  # no role

    async with WsTestClient(main.app, f"/ws/activity/{comp}") as ws:
        await ws.send_json({"token": member})
        assert (await ws.receive_json())["type"] == "auth_ok"
        # Broadcast-only room: no snapshot follows auth_ok.
        await _expect_silence(ws)

    async with WsTestClient(main.app, f"/ws/activity/{comp}") as ws:
        await ws.send_json({"token": outsider})
        assert await ws.expect_close() == 4403

    async with WsTestClient(main.app, "/ws/activity/not-a-competition") as ws:
        admin = await admin_token(client)
        await ws.send_json({"token": admin})
        assert await ws.expect_close() == 4403


async def test_wrong_submission_pings_attempted(client):
    """A graded-but-wrong flag now emits challenge.attempted (§3.2) and the
    room hears it — the stale-attempt-counters half of #18."""
    comp, chal = await _competition_with_challenge(client)
    watcher = await _joined_participant(client, comp, "watcher@example.com", "Watch")
    actor = await _joined_participant(client, comp, "actor@example.com", "Act")

    async with WsTestClient(main.app, f"/ws/activity/{comp}") as ws:
        await ws.send_json({"token": watcher})
        assert (await ws.receive_json())["type"] == "auth_ok"

        resp = await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/submit",
            json={"flag": "flag{nope}"},
            headers=_auth(actor),
        )
        assert resp.json()["correct"] is False

        frame = await ws.receive_json()
        # Ids only, never bodies — the frame is a refetch cue, not data.
        assert frame == {
            "type": "activity",
            "event": "challenge.attempted",
            "challenge_id": chal,
        }
        await _expect_silence(ws)  # wrong guess → no solved ping


async def test_correct_submission_pings_attempted_then_solved(client):
    comp, chal = await _competition_with_challenge(client)
    watcher = await _joined_participant(client, comp, "watcher2@example.com", "W2")
    actor = await _joined_participant(client, comp, "actor2@example.com", "A2")

    async with WsTestClient(main.app, f"/ws/activity/{comp}") as ws:
        await ws.send_json({"token": watcher})
        assert (await ws.receive_json())["type"] == "auth_ok"

        resp = await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/submit",
            json={"flag": "flag{win}"},
            headers=_auth(actor),
        )
        assert resp.json()["correct"] is True

        first = await ws.receive_json()
        assert first["event"] == "challenge.attempted"
        second = await ws.receive_json()
        # The solved ping now carries the challenge's new public solve_count +
        # value as a delta (#188), so watchers patch the card in place instead
        # of refetching the whole list. Static 100-pt challenge → value stays 100.
        # Team mode → the solving team_id rides along so a teammate knows to
        # refetch their shared solved/locked state (public via the solves list).
        assert second["type"] == "activity"
        assert second["event"] == "challenge.solved"
        assert second["challenge_id"] == chal
        assert second["solve_count"] == 1
        assert second["value"] == 100
        assert isinstance(second["team_id"], str) and second["team_id"]


async def test_solve_delta_carries_decayed_value_for_dynamic(client):
    """#188: the delta reflects dynamic re-valuation — a watcher patches the
    lower worth in place without refetching."""
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={"name": "Dyn", "participation_mode": "team", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]
    chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={
                "title": "D",
                "points": 500,
                "scoring_type": "dynamic",
                "min_points": 100,
                "decay": 10,
                "flag": "flag{d}",
            },
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin)
    )
    watcher = await _joined_participant(client, comp, "dw@example.com", "DW")
    actor = await _joined_participant(client, comp, "da@example.com", "DA")

    async with WsTestClient(main.app, f"/ws/activity/{comp}") as ws:
        await ws.send_json({"token": watcher})
        assert (await ws.receive_json())["type"] == "auth_ok"
        await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/submit",
            json={"flag": "flag{d}"},
            headers=_auth(actor),
        )
        assert (await ws.receive_json())["event"] == "challenge.attempted"
        second = await ws.receive_json()
        assert second["event"] == "challenge.solved"
        assert second["solve_count"] == 1
        assert 100 <= second["value"] < 500  # decayed after the first solve, floored


async def test_solve_delta_omitted_under_freeze(client):
    """#188: under a freeze the visible solve_count is per-viewer (staff live vs
    competitor frozen), which one broadcast can't serve — so the delta is
    omitted and clients fall back to refetching their own frozen slice."""
    comp, chal = await _competition_with_challenge(client)
    admin = await admin_token(client)
    watcher = await _joined_participant(client, comp, "fw@example.com", "FW")
    actor = await _joined_participant(client, comp, "fa@example.com", "FA")

    r = await client.post(
        f"/api/competitions/{comp}/scoreboard/freeze", json={}, headers=_auth(admin)
    )
    assert r.status_code == 200

    async with WsTestClient(main.app, f"/ws/activity/{comp}") as ws:
        await ws.send_json({"token": watcher})
        assert (await ws.receive_json())["type"] == "auth_ok"
        await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/submit",
            json={"flag": "flag{win}"},
            headers=_auth(actor),
        )
        assert (await ws.receive_json())["event"] == "challenge.attempted"
        second = await ws.receive_json()
        assert second == {
            "type": "activity",
            "event": "challenge.solved",
            "challenge_id": chal,
        }


async def test_solve_delta_omitted_for_a_hidden_challenge(client):
    """#188 visibility gate: an editor can solve a draft/unreleased challenge,
    but its solve_count/value must not be disclosed to competitors who 404 on
    it — the delta is omitted (the id ping is pre-existing behaviour)."""
    admin = await admin_token(client)
    comp = (
        await client.post(
            "/api/competitions",
            json={
                "name": "CTF",
                "participation_mode": "individual",
                "visibility": "public",
            },
            headers=_auth(admin),
        )
    ).json()["id"]
    # A DRAFT challenge (never published) — hidden from competitors.
    chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Secret", "points": 100, "flag": "flag{draft}"},
            headers=_auth(admin),
        )
    ).json()["id"]
    # A competitor who joined (Participant → challenge_view → can watch activity).
    watcher = await _register(client, "hw@example.com")
    await client.post(f"/api/competitions/{comp}/join", headers=_auth(watcher))

    async with WsTestClient(main.app, f"/ws/activity/{comp}") as ws:
        await ws.send_json({"token": watcher})
        assert (await ws.receive_json())["type"] == "auth_ok"
        # The admin (an editor) solves the draft — allowed for editors.
        r = await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/submit",
            json={"flag": "flag{draft}"},
            headers=_auth(admin),
        )
        assert r.json()["correct"] is True
        # attempted, then solved — but with NO delta (hidden challenge).
        assert (await ws.receive_json())["event"] == "challenge.attempted"
        second = await ws.receive_json()
        assert second == {
            "type": "activity",
            "event": "challenge.solved",
            "challenge_id": chal,
        }


async def test_ticket_events_do_not_reach_the_activity_room(client):
    """ticket.* stays out of the allowlist — tickets have their own
    opener/staff-scoped rooms, and a competitor's activity socket must not
    learn that someone opened one."""
    comp, chal = await _competition_with_challenge(client)
    watcher = await _joined_participant(client, comp, "quiet@example.com", "Q")
    opener = await _joined_participant(client, comp, "stuck@example.com", "S")

    async with WsTestClient(main.app, f"/ws/activity/{comp}") as ws:
        await ws.send_json({"token": watcher})
        assert (await ws.receive_json())["type"] == "auth_ok"

        resp = await client.post(
            f"/api/competitions/{comp}/tickets",
            json={"subject": "Help", "body": "Stuck", "challenge_id": chal},
            headers=_auth(opener),
        )
        assert resp.status_code == 201, resp.text
        await _expect_silence(ws)


async def test_team_created_pings_the_room(client):
    """team.created is allowlisted — the roster/stat surfaces refresh when a
    new team forms (team creation grants membership without a separate
    member_joined emit, so this is the join signal in team mode)."""
    comp, _ = await _competition_with_challenge(client)
    watcher = await _joined_participant(client, comp, "early@example.com", "Early")

    async with WsTestClient(main.app, f"/ws/activity/{comp}") as ws:
        await ws.send_json({"token": watcher})
        assert (await ws.receive_json())["type"] == "auth_ok"

        await _joined_participant(client, comp, "late@example.com", "Late")
        frame = await ws.receive_json()
        # Ids-only ping; no challenge_id key for a non-challenge event.
        assert frame == {"type": "activity", "event": "team.created"}


async def test_thread_reply_bumps_the_support_room(client):
    """A ticket reply now pings the staff queue (ticket_updated, no cue) so
    open-thread activity is visible without entering the thread."""
    comp, chal = await _competition_with_challenge(client)
    admin = await admin_token(client)
    opener = await _joined_participant(client, comp, "replier@example.com", "R")
    ticket = (
        await client.post(
            f"/api/competitions/{comp}/tickets",
            json={"subject": "Help", "body": "Stuck", "challenge_id": chal},
            headers=_auth(opener),
        )
    ).json()["id"]

    async with WsTestClient(main.app, f"/ws/support/{comp}") as ws:
        await ws.send_json({"token": admin})
        assert (await ws.receive_json())["type"] == "auth_ok"

        resp = await client.post(
            f"/api/competitions/{comp}/tickets/{ticket}/messages",
            json={"body": "any update?"},
            headers=_auth(opener),
        )
        assert resp.status_code == 200, resp.text
        frame = await ws.receive_json()
        assert frame == {"type": "ticket_updated", "ticket_id": ticket}
