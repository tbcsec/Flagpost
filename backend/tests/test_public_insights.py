"""Public spectator insights + points timeline (#24).

The security-critical property here is **freeze parity**: the spectator board is
always computed as of the freeze cutoff, so every number served alongside it
must be too. The other invariant worth guarding is that each timeline series
ends exactly on that subject's board total — the chart and the table sit on the
same page and must not disagree.
"""

import pytest

from config import settings
from tests.conftest import admin_token


@pytest.fixture(autouse=True)
def _no_insights_cache():
    """The endpoint memoises for a few seconds in production; these tests mutate
    and immediately re-read, so turn it off."""
    original = settings.public_insights_cache_seconds
    settings.public_insights_cache_seconds = 0
    yield
    settings.public_insights_cache_seconds = original


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _public_competition(client, **overrides) -> str:
    admin = await admin_token(client)
    body = {
        "name": "Open CTF",
        "participation_mode": "individual",
        # `visibility` gates self-join; `public_scoreboard` gates the spectator
        # routes — separate opt-ins (Phase 9).
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


async def _insights(client, comp: str):
    # No Authorization header anywhere — this is the unauthenticated surface.
    return await client.get(f"/api/public/competitions/{comp}/insights")


async def _board_points(client, comp: str) -> dict[str, int]:
    board = (
        await client.get(f"/api/public/competitions/{comp}/scoreboard")
    ).json()
    return {e["subject_id"]: e["points"] for e in board["entries"]}


# --- gating ------------------------------------------------------------------


async def test_insights_only_for_opted_in_competitions(client):
    admin = await admin_token(client)
    opted_in = await _public_competition(client)
    private = (
        await client.post(
            "/api/competitions",
            json={"name": "Closed CTF", "participation_mode": "individual"},
            headers=_auth(admin),
        )
    ).json()["id"]

    assert (await _insights(client, opted_in)).status_code == 200
    # An opted-out competition is never disclosed, same 404 as a missing one.
    assert (await _insights(client, private)).status_code == 404
    assert (await _insights(client, "does-not-exist")).status_code == 404


async def test_archived_competition_insights_are_hidden(client):
    admin = await admin_token(client)
    comp = await _public_competition(client)
    await client.post(f"/api/competitions/{comp}/archive", headers=_auth(admin))
    assert (await _insights(client, comp)).status_code == 404


async def test_empty_competition_returns_zeros_not_an_error(client):
    comp = await _public_competition(client)
    body = (await _insights(client, comp)).json()
    assert body["stats"] == {
        "participants": 0,
        "solves": 0,
        "challenges": 0,
        "unsolved": 0,
    }
    assert body["highlights"]["most_solved"] is None
    assert body["highlights"]["fastest_solve"] is None
    assert body["timeline"]["series"] == []


# --- stats + highlights ------------------------------------------------------


async def test_stats_and_highlights_reflect_play(client):
    comp = await _public_competition(client)
    easy = await _challenge(client, comp, "Easy", "flag{easy}", 100)
    hard = await _challenge(client, comp, "Hard", "flag{hard}", 300)
    await _challenge(client, comp, "Untouched", "flag{none}", 500)

    ada, _ = await _player(client, comp, "ada")
    bob, _ = await _player(client, comp, "bob")

    # Ada first-bloods both solved challenges; Bob follows on the easy one and
    # burns two failed attempts on the hard one.
    await _submit(client, comp, easy, ada, "flag{easy}")
    await _submit(client, comp, hard, ada, "flag{hard}")
    await _submit(client, comp, easy, bob, "flag{easy}")
    await _submit(client, comp, hard, bob, "nope")
    await _submit(client, comp, hard, bob, "still-nope")

    body = (await _insights(client, comp)).json()
    assert body["stats"] == {
        "participants": 2,
        "solves": 3,
        "challenges": 3,
        "unsolved": 1,  # "Untouched"
    }
    highlights = body["highlights"]
    assert highlights["most_solved"] == {"title": "Easy", "count": 2}
    # Hard: 1 solve + 2 fails = 3 submissions, more than Easy's 2.
    assert highlights["most_attempted"] == {"title": "Hard", "count": 3}
    assert highlights["first_blood_leader"] == {"name": "ada", "count": 2}
    assert highlights["fastest_solve"]["name"] == "ada"
    assert highlights["fastest_solve"]["seconds"] >= 0


async def test_drafts_and_unreleased_challenges_are_not_disclosed(client):
    """A spectator must not learn that an unpublished — or not-yet-released —
    challenge exists."""
    from datetime import timedelta

    from db import utcnow

    admin = await admin_token(client)
    comp = await _public_competition(client)
    await _challenge(client, comp, "Live", "flag{live}", 100)
    # A draft (never published).
    await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "Draft", "points": 100, "flag": "flag{draft}"},
        headers=_auth(admin),
    )
    # Published but scheduled for a future wave.
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

    body = (await _insights(client, comp)).json()
    assert body["stats"]["challenges"] == 1  # only "Live" counts


# --- timeline ----------------------------------------------------------------


async def test_timeline_series_end_on_the_board_totals(client):
    """The four point sources — solves, hint costs, score adjustments and award
    points — must all reach the timeline, or the chart would contradict the
    table beside it."""
    from db import SessionLocal
    from models.automation import Achievement
    from models.score_adjustment import ScoreAdjustment

    comp = await _public_competition(client)
    chal = await _challenge(client, comp, "Solve me", "flag{go}", 100)
    admin = await admin_token(client)
    hint = (
        await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/hints",
            json={"body": "a nudge", "cost": 10},
            headers=_auth(admin),
        )
    ).json()["id"]

    ada, ada_id = await _player(client, comp, "ada")
    await _submit(client, comp, chal, ada, "flag{go}")
    # Pay a hint cost (−10).
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/hints/{hint}/reveal",
        headers=_auth(ada),
    )
    # A judge bonus (+25) and a point-bearing award (+50).
    async with SessionLocal() as db:
        db.add(
            ScoreAdjustment(
                competition_id=comp, user_id=ada_id, points=25, reason="bonus"
            )
        )
        db.add(
            Achievement(
                competition_id=comp, user_id=ada_id, title="Star", points=50
            )
        )
        await db.commit()

    body = (await _insights(client, comp)).json()
    series = {s["subject_id"]: s for s in body["timeline"]["series"]}
    board = await _board_points(client, comp)

    assert board[ada_id] == 100 - 10 + 25 + 50 == 165
    ada_points = series[ada_id]["points"]
    assert ada_points[-1]["points"] == board[ada_id]
    # Monotonic in time, and seeded at zero from the competition start.
    times = [p["t"] for p in ada_points]
    assert times == sorted(times)
    assert ada_points[0]["points"] == 0


async def test_timeline_caps_at_ten_subjects(client):
    comp = await _public_competition(client)
    chal = await _challenge(client, comp, "Only", "flag{x}", 100)
    for i in range(12):
        token, _ = await _player(client, comp, f"player{i:02d}")
        await _submit(client, comp, chal, token, "flag{x}")

    body = (await _insights(client, comp)).json()
    assert body["stats"]["participants"] == 12
    assert len(body["timeline"]["series"]) == 10  # bounded, top-ranked only


# --- freeze parity (the security-critical one) -------------------------------


async def test_freeze_hides_later_activity_from_insights(client):
    comp = await _public_competition(client)
    first = await _challenge(client, comp, "First", "flag{1}", 100)
    second = await _challenge(client, comp, "Second", "flag{2}", 250)
    admin = await admin_token(client)

    ada, ada_id = await _player(client, comp, "ada")
    await _submit(client, comp, first, ada, "flag{1}")

    live = (await _insights(client, comp)).json()
    assert live["frozen"] is False
    assert live["stats"]["solves"] == 1

    # Freeze, then keep playing.
    assert (
        await client.post(
            f"/api/competitions/{comp}/scoreboard/freeze",
            json={},
            headers=_auth(admin),
        )
    ).status_code == 200
    await _submit(client, comp, second, ada, "flag{2}")

    frozen = (await _insights(client, comp)).json()
    assert frozen["frozen"] is True
    # The post-freeze solve is invisible in every derived figure...
    assert frozen["stats"]["solves"] == 1
    assert frozen["stats"]["unsolved"] == 1
    assert frozen["highlights"]["most_solved"] == {"title": "First", "count": 1}
    # ...including the timeline, which still agrees with the frozen board.
    board = await _board_points(client, comp)
    series = frozen["timeline"]["series"][0]
    assert board[ada_id] == 100
    assert series["points"][-1]["points"] == 100

    # Unfreezing reveals it again.
    await client.post(
        f"/api/competitions/{comp}/scoreboard/unfreeze", headers=_auth(admin)
    )
    after = (await _insights(client, comp)).json()
    assert after["frozen"] is False
    assert after["stats"]["solves"] == 2
    assert after["timeline"]["series"][0]["points"][-1]["points"] == 350
