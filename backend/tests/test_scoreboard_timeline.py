"""Authenticated scoreboard points-over-time timeline (#348).

The chart sits beside the standings table, so its invariants are the board's:
each series ends on that subject's board total, a freeze hides later movement
from competitors but not from a ``scoreboard_freeze`` holder, and a ``bracket``
scopes the series to one division exactly as it scopes the table. Plus the new
one this endpoint adds: the payload stays bounded (top-N + downsampling) for a
long event.
"""

from datetime import datetime, timedelta, timezone

import pytest

from config import settings
from tests.conftest import admin_token
from utils.scoreboard_timeline import _downsample


@pytest.fixture(autouse=True)
def _no_timeline_cache():
    """The endpoint memoises for a few seconds in production; these tests mutate
    then immediately re-read, so turn it off (shared TTL knob with insights)."""
    original = settings.public_insights_cache_seconds
    settings.public_insights_cache_seconds = 0
    yield
    settings.public_insights_cache_seconds = original


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _competition(client, **overrides) -> str:
    admin = await admin_token(client)
    body = {
        "name": "CTF",
        "participation_mode": "individual",
        # Public visibility so players can self-join and gain challenge_view.
        "visibility": "public",
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


async def _timeline(client, comp: str, token: str, **params):
    return await client.get(
        f"/api/competitions/{comp}/scoreboard/timeline",
        params=params,
        headers=_auth(token),
    )


async def _board_points(client, comp: str, token: str) -> dict[str, int]:
    board = (
        await client.get(f"/api/competitions/{comp}/scoreboard", headers=_auth(token))
    ).json()
    return {e["subject_id"]: e["points"] for e in board["entries"]}


# --- endpoint behaviour ------------------------------------------------------


async def test_series_ends_on_the_board_total(client):
    comp = await _competition(client)
    c1 = await _challenge(client, comp, "One", "flag{1}", 100)
    c2 = await _challenge(client, comp, "Two", "flag{2}", 250)
    ada, ada_id = await _player(client, comp, "ada")
    await _submit(client, comp, c1, ada, "flag{1}")
    await _submit(client, comp, c2, ada, "flag{2}")

    resp = await _timeline(client, comp, ada)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    series = {s["subject_id"]: s for s in body["series"]}
    points = series[ada_id]["points"]

    board = await _board_points(client, comp, ada)
    assert points[-1]["points"] == board[ada_id] == 350
    # Seeded at zero from the start, and monotonic in time.
    assert points[0]["points"] == 0
    times = [p["t"] for p in points]
    assert times == sorted(times)


async def test_top_param_bounds_the_series_count(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp, "Only", "flag{x}", 100)
    for i in range(5):
        token, _ = await _player(client, comp, f"p{i}")
        await _submit(client, comp, chal, token, "flag{x}")
    viewer, _ = await _player(client, comp, "viewer")

    two = (await _timeline(client, comp, viewer, top=2)).json()
    assert len(two["series"]) == 2

    # Over-large top is clamped, not honoured verbatim: only 6 subjects exist.
    lots = (await _timeline(client, comp, viewer, top=1000)).json()
    assert len(lots["series"]) == 6


async def test_bracket_scopes_the_series(client):
    from db import SessionLocal
    from models.bracket import BracketMembership

    comp = await _competition(client)
    chal = await _challenge(client, comp, "Only", "flag{x}", 100)
    ada, ada_id = await _player(client, comp, "ada")
    bo, bo_id = await _player(client, comp, "bo")
    await _submit(client, comp, chal, ada, "flag{x}")
    await _submit(client, comp, chal, bo, "flag{x}")
    async with SessionLocal() as db:
        db.add(BracketMembership(competition_id=comp, subject_id=ada_id, bracket="A"))
        db.add(BracketMembership(competition_id=comp, subject_id=bo_id, bracket="B"))
        await db.commit()

    only_a = (await _timeline(client, comp, ada, bracket="A")).json()
    assert [s["subject_id"] for s in only_a["series"]] == [ada_id]


async def test_freeze_hides_later_movement_but_staff_can_bypass(client):
    comp = await _competition(client)
    c1 = await _challenge(client, comp, "First", "flag{1}", 100)
    c2 = await _challenge(client, comp, "Second", "flag{2}", 200)
    admin = await admin_token(client)
    ada, ada_id = await _player(client, comp, "ada")

    await _submit(client, comp, c1, ada, "flag{1}")
    await client.post(
        f"/api/competitions/{comp}/scoreboard/freeze", json={}, headers=_auth(admin)
    )
    await _submit(client, comp, c2, ada, "flag{2}")  # after the freeze

    # A competitor sees the frozen picture: only the pre-freeze 100.
    frozen = (await _timeline(client, comp, ada)).json()
    ada_frozen = {s["subject_id"]: s for s in frozen["series"]}[ada_id]["points"]
    assert ada_frozen[-1]["points"] == 100

    # ?live=true is ignored for a competitor (no scoreboard_freeze permission).
    still_frozen = (await _timeline(client, comp, ada, live=True)).json()
    ada_still = {s["subject_id"]: s for s in still_frozen["series"]}[ada_id]["points"]
    assert ada_still[-1]["points"] == 100

    # Staff with ?live=true see the true 300.
    live = (await _timeline(client, comp, admin, live=True)).json()
    ada_live = {s["subject_id"]: s for s in live["series"]}[ada_id]["points"]
    assert ada_live[-1]["points"] == 300


async def test_timeline_requires_authentication(client):
    comp = await _competition(client)
    resp = await client.get(f"/api/competitions/{comp}/scoreboard/timeline")
    assert resp.status_code == 401


async def test_timeline_cache_is_dropped_on_a_solve(client):
    # The chart is a cached read; a scoring event must invalidate it so it never
    # lags the table beside it, rather than waiting out the TTL.
    settings.public_insights_cache_seconds = 30  # cache ON just for this test
    try:
        comp = await _competition(client)
        chal = await _challenge(client, comp, "One", "flag{1}", 100)
        ada, ada_id = await _player(client, comp, "ada")
        # Prime the cache while nobody has scored.
        primed = (await _timeline(client, comp, ada)).json()
        assert all(
            all(p["points"] == 0 for p in s["points"]) for s in primed["series"]
        )
        await _submit(client, comp, chal, ada, "flag{1}")
        # The next read reflects the solve — the cache was dropped, not stale.
        after = (await _timeline(client, comp, ada)).json()
        series = {s["subject_id"]: s for s in after["series"]}
        assert series[ada_id]["points"][-1]["points"] == 100
    finally:
        settings.public_insights_cache_seconds = 0


# --- downsampling (pure) -----------------------------------------------------

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ramp(n: int) -> list[tuple[datetime, int]]:
    """A cumulative ramp: n points, one per minute, points 0..n-1."""
    return [(_T0 + timedelta(minutes=i), i) for i in range(n)]


def test_downsample_is_a_noop_below_the_cap():
    raw = _ramp(50)
    assert _downsample(raw, 400) is raw


def test_downsample_caps_count_and_keeps_the_endpoints():
    raw = _ramp(5000)
    out = _downsample(raw, 400)
    assert len(out) <= 400
    assert out[0] == raw[0]  # baseline zero preserved
    assert out[-1] == raw[-1]  # final cumulative (the board total) preserved
    # Still time-ordered, and every kept point is a real (t, points) pair.
    times = [t for t, _ in out]
    assert times == sorted(times)
    assert set(out).issubset(set(raw))


def test_downsample_caps_even_for_pathological_max_points():
    # Regression: max_points < 3 once returned the whole series (blowing the
    # cap). It must still reduce to the two endpoints.
    raw = _ramp(100)
    assert _downsample(raw, 1) == [raw[0], raw[-1]]
    assert _downsample(raw, 2) == [raw[0], raw[-1]]


def test_downsample_degenerate_single_instant():
    # More points than the cap but all at one timestamp — nothing meaningful to
    # bucket, so collapse to the endpoints.
    raw = [(_T0, 0), (_T0, 3), (_T0, 6), (_T0, 9)]
    assert _downsample(raw, 3) == [(_T0, 0), (_T0, 9)]
