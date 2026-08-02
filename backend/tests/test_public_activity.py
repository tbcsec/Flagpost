"""Public recent-solves feed for venue mode (#77).

Same security posture as the insights it sits beside: unauthenticated, opt-in
gated, and **freeze-aware** — a solve after the cutoff must not appear (or the
first-blood splash would leak the movement the frozen board is hiding). Also
guards that only visible (published + released) challenges are disclosed and
that first-blood tagging matches the earliest awarded solve.
"""

import pytest

from config import settings
from tests.conftest import admin_token


@pytest.fixture(autouse=True)
def _no_activity_cache():
    """The feed memoises for a few seconds in production; these tests mutate and
    immediately re-read, so turn it off."""
    original = settings.public_activity_cache_seconds
    settings.public_activity_cache_seconds = 0
    yield
    settings.public_activity_cache_seconds = original


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _public_competition(client, **overrides) -> str:
    admin = await admin_token(client)
    body = {
        "name": "Open CTF",
        "participation_mode": "individual",
        "visibility": "public",
        "public_scoreboard": True,
        **overrides,
    }
    resp = await client.post("/api/competitions", json=body, headers=_auth(admin))
    return resp.json()["id"]


async def _challenge(client, comp: str, title: str, flag: str, points: int) -> str:
    admin = await admin_token(client)
    chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": title, "points": points, "flag": flag},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin)
    )
    return chal


async def _player(client, comp: str, name: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={"display_name": name, "password": "password123"},
    )
    token, user_id = resp.json()["access_token"], resp.json()["user"]["id"]
    await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    return token, user_id


async def _submit(client, comp: str, chal: str, token: str, flag: str):
    return await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": flag},
        headers=_auth(token),
    )


async def _activity(client, comp: str):
    # No Authorization header — this is the unauthenticated surface.
    return await client.get(f"/api/public/competitions/{comp}/activity")


# --- gating ------------------------------------------------------------------


async def test_activity_only_for_opted_in_competitions(client):
    admin = await admin_token(client)
    opted_in = await _public_competition(client)
    private = (
        await client.post(
            "/api/competitions",
            json={"name": "Closed CTF", "participation_mode": "individual"},
            headers=_auth(admin),
        )
    ).json()["id"]

    assert (await _activity(client, opted_in)).status_code == 200
    assert (await _activity(client, private)).status_code == 404
    assert (await _activity(client, "does-not-exist")).status_code == 404


async def test_archived_competition_activity_is_hidden(client):
    admin = await admin_token(client)
    comp = await _public_competition(client)
    await client.post(f"/api/competitions/{comp}/archive", headers=_auth(admin))
    assert (await _activity(client, comp)).status_code == 404


async def test_empty_competition_returns_no_solves(client):
    comp = await _public_competition(client)
    body = (await _activity(client, comp)).json()
    assert body == {"recent_solves": []}


# --- content -----------------------------------------------------------------


async def test_recent_solves_newest_first_with_first_blood_tagging(client):
    comp = await _public_competition(client)
    easy = await _challenge(client, comp, "Easy", "flag{easy}", 100)
    hard = await _challenge(client, comp, "Hard", "flag{hard}", 300)

    ada, _ = await _player(client, comp, "ada")
    bob, _ = await _player(client, comp, "bob")

    # ada first-bloods Easy; bob then solves Easy (a plain solve); bob first-bloods
    # Hard last, so it should sit at the top of the feed.
    await _submit(client, comp, easy, ada, "flag{easy}")
    await _submit(client, comp, easy, bob, "flag{easy}")
    await _submit(client, comp, hard, bob, "flag{hard}")

    solves = (await _activity(client, comp)).json()["recent_solves"]
    assert len(solves) == 3

    # Newest-first ordering.
    times = [s["solved_at"] for s in solves]
    assert times == sorted(times, reverse=True)
    assert solves[0]["title"] == "Hard"
    assert solves[0]["subject_name"] == "bob"

    # First-blood tagging keys on the earliest solve of each challenge.
    by_pair = {(s["title"], s["subject_name"]): s for s in solves}
    assert by_pair[("Easy", "ada")]["is_first_blood"] is True
    assert by_pair[("Easy", "bob")]["is_first_blood"] is False
    assert by_pair[("Hard", "bob")]["is_first_blood"] is True
    assert by_pair[("Easy", "ada")]["points"] == 100


async def test_drafts_and_unreleased_solves_are_not_disclosed(client):
    """A solve of a not-yet-visible challenge must not leak through the feed."""
    from datetime import timedelta

    from db import utcnow

    admin = await admin_token(client)
    comp = await _public_competition(client)
    live = await _challenge(client, comp, "Live", "flag{live}", 100)
    # Published but scheduled for a future wave — spectators mustn't see it, or a
    # solve of it, yet.
    future = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={
                "title": "Later",
                "points": 100,
                "flag": "flag{later}",
                "release_at": (utcnow() + timedelta(hours=1)).isoformat(),
            },
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{future}/publish", headers=_auth(admin)
    )

    ada, _ = await _player(client, comp, "ada")
    await _submit(client, comp, live, ada, "flag{live}")
    # Staff can submit to a scheduled challenge; that solve must still be hidden.
    await _submit(client, comp, future, await admin_token(client), "flag{later}")

    solves = (await _activity(client, comp)).json()["recent_solves"]
    assert [s["title"] for s in solves] == ["Live"]


# --- freeze parity (the security-critical one) -------------------------------


async def test_freeze_hides_later_solves_from_the_feed(client):
    comp = await _public_competition(client)
    first = await _challenge(client, comp, "First", "flag{1}", 100)
    second = await _challenge(client, comp, "Second", "flag{2}", 250)
    admin = await admin_token(client)

    ada, _ = await _player(client, comp, "ada")
    await _submit(client, comp, first, ada, "flag{1}")

    assert len((await _activity(client, comp)).json()["recent_solves"]) == 1

    # Freeze, then keep playing.
    assert (
        await client.post(
            f"/api/competitions/{comp}/scoreboard/freeze",
            json={},
            headers=_auth(admin),
        )
    ).status_code == 200
    await _submit(client, comp, second, ada, "flag{2}")

    # The post-freeze solve is invisible — a frozen board emits no new splash.
    frozen = (await _activity(client, comp)).json()["recent_solves"]
    assert [s["title"] for s in frozen] == ["First"]

    # Unfreezing reveals it again.
    await client.post(
        f"/api/competitions/{comp}/scoreboard/unfreeze", headers=_auth(admin)
    )
    after = (await _activity(client, comp)).json()["recent_solves"]
    assert {s["title"] for s in after} == {"First", "Second"}
