"""Announcement severity + audience targeting (#40).

The load-bearing property: a targeted announcement must be invisible to
non-recipients on *every* path — the REST list, the WS join snapshot, and the
live broadcast — and `critical` is the one tier that overrides a muted in-app
notification category.
"""

import asyncio

import pytest

from tests.conftest import admin_token
from tests.ws_client import WsTestClient
from utils.event_bus import event_bus

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
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


async def _me_id(client, token: str) -> str:
    return (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]


async def _competition(client, admin: str, mode: str = "team") -> str:
    # Public so a registered user can self-serve join (§7.5) — the individual-mode
    # tests below rely on it, matching the test_participants idiom.
    resp = await client.post(
        "/api/competitions",
        json={
            "name": f"CTF {mode}",
            "participation_mode": mode,
            "visibility": "public",
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _joined(client, comp: str, email: str) -> str:
    """Register + join an individual-mode competition; returns the token."""
    token = await _register(client, email)
    resp = await client.post(
        f"/api/competitions/{comp}/join", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    return token


async def _member_with_team(client, comp: str, email: str, team: str) -> tuple[str, str]:
    """Register, join `comp` by creating team `team`. Returns (token, team_id)."""
    token = await _register(client, email)
    resp = await client.post(
        f"/api/competitions/{comp}/teams", json={"name": team}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    return token, resp.json()["id"]


async def _post(client, comp: str, token: str, **kwargs):
    body = {"title": "T", "body": "B", **kwargs}
    resp = await client.post(
        f"/api/competitions/{comp}/announcements", json=body, headers=_auth(token)
    )
    # Delivery (notification rows + WS fan-out) is on the background lane now
    # (#176), so drain it before asserting on the delivered effects.
    await event_bus.wait_for_background()
    return resp


async def _titles(client, comp: str, token: str) -> list[str]:
    resp = await client.get(
        f"/api/competitions/{comp}/announcements", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    return [a["title"] for a in resp.json()]


async def _notifications(client, token: str) -> list[dict]:
    return (await client.get("/api/notifications", headers=_auth(token))).json()


async def _expect_silence(ws: WsTestClient, timeout: float = 0.3) -> None:
    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        await ws.next_message(timeout)


# --- severity ---------------------------------------------------------------


async def test_severity_defaults_to_info_and_round_trips(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)

    assert (await _post(client, comp, admin)).json()["severity"] == "info"
    resp = await _post(client, comp, admin, title="Urgent", severity="critical")
    assert resp.json()["severity"] == "critical"

    resp = await _post(client, comp, admin, severity="nonsense")
    assert resp.status_code == 422


# --- audience: read filtering ------------------------------------------------


async def test_user_targeted_announcement_is_invisible_to_others(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin, mode="individual")
    alice = await _joined(client, comp, "alice@example.com")
    bob = await _joined(client, comp, "bob@example.com")
    alice_id = await _me_id(client, alice)

    await _post(client, comp, admin, title="Everyone")
    await _post(
        client, comp, admin, title="For Alice",
        audience_type="users", audience_ids=[alice_id],
    )

    assert await _titles(client, comp, alice) == ["For Alice", "Everyone"]
    assert await _titles(client, comp, bob) == ["Everyone"]
    # Staff see everything — it's their own sent history, not a leak.
    assert await _titles(client, comp, admin) == ["For Alice", "Everyone"]


async def test_team_targeted_announcement_follows_membership(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    red_token, red_id = await _member_with_team(client, comp, "red@example.com", "Red")
    blue_token, _ = await _member_with_team(client, comp, "blue@example.com", "Blue")

    await _post(
        client, comp, admin, title="Red only",
        audience_type="teams", audience_ids=[red_id],
    )

    assert await _titles(client, comp, red_token) == ["Red only"]
    assert await _titles(client, comp, blue_token) == []


async def test_targeted_announcement_requires_recipients(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    resp = await _post(client, comp, admin, audience_type="users", audience_ids=[])
    assert resp.status_code == 422


async def test_audience_ids_cleared_for_everyone(client):
    """An "all" row must not carry ids that could imply a narrower audience."""
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    resp = await _post(
        client, comp, admin, audience_type="all", audience_ids=["stray-id"]
    )
    assert resp.json()["audience_ids"] == []


# --- audience: delivery ------------------------------------------------------


async def test_targeted_announcement_never_reaches_the_shared_room(client):
    """The leak test. The shared room fans to every member, so a targeted
    announcement must not be broadcast there — only "all" may use it."""
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    outsider, _ = await _member_with_team(client, comp, "out@example.com", "Out")
    _, target_team = await _member_with_team(client, comp, "in@example.com", "In")

    async with WsTestClient(main.app, f"/ws/announcements/{comp}") as ws:
        await ws.send_json({"token": outsider})
        assert (await ws.receive_json())["type"] == "auth_ok"
        assert (await ws.receive_json())["type"] == "announcements"  # snapshot

        await _post(
            client, comp, admin, title="Secret",
            audience_type="teams", audience_ids=[target_team],
        )
        await _expect_silence(ws)

        # A whole-competition announcement still takes the shared fast path.
        await _post(client, comp, admin, title="Public")
        frame = await ws.receive_json()
        assert frame["type"] == "announcement"
        assert frame["announcement"]["title"] == "Public"
        assert frame["announcement"]["severity"] == "info"


async def test_join_snapshot_is_audience_filtered(client):
    """A reconnect must not reveal what the live path withheld."""
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    outsider, _ = await _member_with_team(client, comp, "out2@example.com", "Out2")
    _, target_team = await _member_with_team(client, comp, "in2@example.com", "In2")

    await _post(client, comp, admin, title="Everyone")
    await _post(
        client, comp, admin, title="Secret",
        audience_type="teams", audience_ids=[target_team],
    )

    async with WsTestClient(main.app, f"/ws/announcements/{comp}") as ws:
        await ws.send_json({"token": outsider})
        assert (await ws.receive_json())["type"] == "auth_ok"
        snapshot = await ws.receive_json()
        assert [a["title"] for a in snapshot["announcements"]] == ["Everyone"]


# --- notifications -----------------------------------------------------------


async def test_announcement_notifies_recipients_only(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin, mode="individual")
    alice = await _joined(client, comp, "alice2@example.com")
    bob = await _joined(client, comp, "bob2@example.com")
    alice_id = await _me_id(client, alice)

    await _post(
        client, comp, admin, title="Just Alice",
        audience_type="users", audience_ids=[alice_id],
    )

    assert [n["title"] for n in await _notifications(client, alice)] == ["Just Alice"]
    assert await _notifications(client, bob) == []


async def test_user_targeted_announcement_ignores_out_of_competition_ids(client):
    """A users-targeted list can't deliver a notification to a user outside the
    competition (#5) — resolve_recipients scopes the raw ids to members."""
    admin = await admin_token(client)
    comp = await _competition(client, admin, mode="individual")
    member = await _joined(client, comp, "member@example.com")
    member_id = await _me_id(client, member)
    # An outsider: registered, but never joined this competition.
    outsider = await _register(client, "outsider@example.com")
    outsider_id = await _me_id(client, outsider)

    await _post(
        client, comp, admin, title="Targeted",
        audience_type="users", audience_ids=[member_id, outsider_id],
    )

    assert [n["title"] for n in await _notifications(client, member)] == ["Targeted"]
    assert await _notifications(client, outsider) == []


async def test_critical_overrides_a_muted_category(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin, mode="individual")
    ada = await _joined(client, comp, "ada@example.com")

    resp = await client.put(
        "/api/notifications/preferences",
        json={"inapp_announcements": False},
        headers=_auth(ada),
    )
    assert resp.status_code == 200, resp.text

    # Muted: an ordinary announcement creates no notification…
    await _post(client, comp, admin, title="Routine")
    assert await _notifications(client, ada) == []

    # …but critical overrides the mute — the one sanctioned bypass (§4.4).
    await _post(client, comp, admin, title="Evacuate", severity="critical")
    assert [n["title"] for n in await _notifications(client, ada)] == ["Evacuate"]


async def test_muting_announcements_leaves_tickets_alone(client):
    """The new category is independent — muting announcements must not mute
    ticket notifications."""
    admin = await admin_token(client)
    comp = await _competition(client, admin, mode="individual")
    ada = await _joined(client, comp, "ada2@example.com")
    await client.put(
        "/api/notifications/preferences",
        json={"inapp_announcements": False},
        headers=_auth(ada),
    )

    resp = await client.post(
        f"/api/competitions/{comp}/tickets",
        json={"subject": "Help", "body": "Stuck"},
        headers=_auth(ada),
    )
    assert resp.status_code == 201, resp.text
    # The admin (staff) still gets the ticket notification.
    assert [n["type"] for n in await _notifications(client, admin)] == [
        "ticket.created"
    ]
