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


async def _drain_and_expect_silence(ws, timeout: float = 0.3) -> None:
    """Let every background broadcast run, then assert none reached ``ws``."""
    import asyncio

    from utils.event_bus import event_bus

    await event_bus.wait_for_background()
    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        await ws.next_message(timeout)


async def test_frozen_scoreboard_room_is_silent_on_post_cutoff_solves(client):
    """GHSA-r7j2: under a freeze every member already holds the frozen board, so
    re-sending it on a post-cutoff solve carries nothing but the solve's timing.
    The room stays quiet until the frozen board actually changes — here, the
    unfreeze, which proves the room was still delivering all along."""
    comp, chal = await _competition_with_challenge(client)
    admin = await admin_token(client)
    watcher = await _joined_participant(client, comp, "fwatch@example.com", "Watch")
    actor = await _joined_participant(client, comp, "fact@example.com", "Act")

    # Freeze while nobody watches: the room's first member is the one who joins.
    r = await client.post(
        f"/api/competitions/{comp}/scoreboard/freeze", json={}, headers=_auth(admin)
    )
    assert r.status_code == 200

    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": watcher})
        assert (await ws.receive_json())["type"] == "auth_ok"
        snapshot = await ws.receive_json()
        assert snapshot["frozen"] is True

        solved = await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/submit",
            json={"flag": "flag{win}"},
            headers=_auth(actor),
        )
        assert solved.json()["correct"] is True
        await _drain_and_expect_silence(ws)

        await client.post(
            f"/api/competitions/{comp}/scoreboard/unfreeze", headers=_auth(admin)
        )
        live = await ws.receive_json()
        assert live["frozen"] is False
        assert {e["name"]: e["points"] for e in live["entries"]} == {
            "Act": 100,
            "Watch": 0,
        }


async def test_frozen_scoreboard_room_still_sends_a_frozen_board_change(client):
    """The flip side: a change dated *before* the cutoff — a backdated code
    judge verdict (ADR-0042 records the solve at submission time), or a rejudge
    revoking it — moves the frozen board itself, so it must still go out."""
    from datetime import timedelta

    from db import SessionLocal, ensure_aware_utc
    from models.challenge import Challenge
    from models.competition import Competition
    from models.submission import Submission
    from models.user import User
    from utils.grading import emit_grade, emit_regrade, record_grade, regrade
    from utils.scoring import resolve_subject

    comp, chal = await _competition_with_challenge(client)
    admin = await admin_token(client)
    watcher = await _joined_participant(client, comp, "bwatch@example.com", "Watch")
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": "bact@example.com",
            "password": "password123",
            "display_name": "bact",
        },
    )
    actor, actor_id = resp.json()["access_token"], resp.json()["user"]["id"]
    assert (
        await client.post(
            f"/api/competitions/{comp}/teams", json={"name": "Act"}, headers=_auth(actor)
        )
    ).status_code == 201
    r = await client.post(
        f"/api/competitions/{comp}/scoreboard/freeze", json={}, headers=_auth(admin)
    )
    assert r.status_code == 200

    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": watcher})
        assert (await ws.receive_json())["type"] == "auth_ok"
        assert (await ws.receive_json())["frozen"] is True

        async with SessionLocal() as db:
            competition = await db.get(Competition, comp)
            challenge = await db.get(Challenge, chal)
            subject = await resolve_subject(db, competition, await db.get(User, actor_id))
            outcome = await record_grade(
                db,
                competition=competition,
                challenge=challenge,
                subject=subject,
                user_id=actor_id,
                value="flag{win}",
                correct=True,
                created_at=ensure_aware_utc(competition.scoreboard_frozen_at)
                - timedelta(seconds=30),
            )
            await db.commit()
        await emit_grade(
            outcome,
            competition_id=comp,
            challenge_id=chal,
            user_id=actor_id,
            team_id=subject.team_id,
        )

        frame = await ws.receive_json()
        assert frame["frozen"] is True
        assert {e["name"]: e["points"] for e in frame["entries"]}["Act"] == 100

        # A rejudge revokes that pre-cutoff solve: the frozen board drops it.
        async with SessionLocal() as db:
            competition = await db.get(Competition, comp)
            revoked = await regrade(
                db,
                competition=competition,
                challenge=await db.get(Challenge, chal),
                subject=subject,
                row=await db.get(Submission, outcome.submission.id),
                correct=False,
            )
            await db.commit()
        assert revoked.revoked
        await emit_regrade(
            revoked,
            competition_id=comp,
            challenge_id=chal,
            user_id=actor_id,
            team_id=subject.team_id,
        )
        frame = await ws.receive_json()
        assert frame["frozen"] is True
        assert {e["name"]: e["points"] for e in frame["entries"]}["Act"] == 0


async def test_frozen_scoreboard_room_cannot_be_rearmed_by_a_silent_board_change(
    client,
):
    """Regression for the board-comparison design: the frozen board also moves
    with no event of its own — a captain renames their team, a new team joins —
    and the next post-cutoff solve then carried that change out, timed to the
    solve. The room decides from the triggering event instead, so a post-cutoff
    solve stays silent whatever changed in between."""
    comp, chal = await _competition_with_challenge(client)
    admin = await admin_token(client)
    spy = await _joined_participant(client, comp, "spy@example.com", "Spy")
    v1 = await _joined_participant(client, comp, "v1@example.com", "V1")
    v2 = await _joined_participant(client, comp, "v2@example.com", "V2")
    r = await client.post(
        f"/api/competitions/{comp}/scoreboard/freeze", json={}, headers=_auth(admin)
    )
    assert r.status_code == 200
    submit = f"/api/competitions/{comp}/challenges/{chal}/submit"

    async with WsTestClient(main.app, f"/ws/scoreboard/{comp}") as ws:
        await ws.send_json({"token": spy})
        assert (await ws.receive_json())["type"] == "auth_ok"
        assert (await ws.receive_json())["frozen"] is True

        renamed = await client.patch(
            f"/api/competitions/{comp}/teams/me",
            json={"name": "Spy2"},
            headers=_auth(spy),
        )
        assert renamed.status_code == 200, renamed.text
        solved = await client.post(submit, json={"flag": "flag{win}"}, headers=_auth(v1))
        assert solved.json()["correct"] is True
        await _drain_and_expect_silence(ws)

        await _joined_participant(client, comp, "late@example.com", "Late")
        solved = await client.post(submit, json={"flag": "flag{win}"}, headers=_auth(v2))
        assert solved.json()["correct"] is True
        await _drain_and_expect_silence(ws)


async def test_challenge_presence_room_closed_to_competitors_unless_running(client):
    """GHSA-r7j2: the #221 status gate — the REST detail 403s a competitor unless
    the competition is running, so the presence room rejects them once it has
    ended (and before it starts). Staff (challenge_edit) are exempt."""
    comp, chal = await _competition_with_challenge(client)
    admin = await admin_token(client)
    token = await _joined_participant(client, comp, "after@example.com", "After")
    stop = await client.post(f"/api/competitions/{comp}/stop", headers=_auth(admin))
    assert stop.status_code == 200, stop.text

    async with WsTestClient(main.app, f"/ws/challenge/{chal}") as ws:
        await ws.send_json({"token": token})
        assert await ws.expect_close() == 4403

    async with WsTestClient(main.app, f"/ws/challenge/{chal}") as ws:
        await ws.send_json({"token": admin})
        assert (await ws.receive_json())["type"] == "auth_ok"
