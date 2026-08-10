"""Cached scoreboard read model (#87 stage 1).

A reconnect herd or spectator poll should compute the board once, not once per
caller; and because every scoreboard-moving event clears the cache, a hit only
ever serves a board that genuinely hasn't changed.
"""

import asyncio
import types

import pytest

from config import settings
from utils import scoreboard as sb


@pytest.fixture(autouse=True)
def _clear_cache():
    sb._scoreboard_cache.clear()
    yield
    sb._scoreboard_cache.clear()


def _comp(cid: str = "c1"):
    return types.SimpleNamespace(id=cid)


async def test_hit_within_ttl_computes_once(monkeypatch):
    n = {"c": 0}

    async def fake(db, competition, *, live=False, bracket=None):
        n["c"] += 1
        return {"entries": [], "call": n["c"]}

    monkeypatch.setattr(sb, "compute_scoreboard", fake)
    b1 = await sb.cached_scoreboard(None, _comp())
    b2 = await sb.cached_scoreboard(None, _comp())
    assert n["c"] == 1  # second read served from cache
    assert b1 is b2


async def test_invalidate_forces_recompute(monkeypatch):
    n = {"c": 0}

    async def fake(db, competition, *, live=False, bracket=None):
        n["c"] += 1
        return {"call": n["c"]}

    monkeypatch.setattr(sb, "compute_scoreboard", fake)
    await sb.cached_scoreboard(None, _comp())
    sb.invalidate_scoreboard("c1")
    await sb.cached_scoreboard(None, _comp())
    assert n["c"] == 2


async def test_ttl_expiry_recomputes(monkeypatch):
    monkeypatch.setattr(settings, "scoreboard_cache_ttl_seconds", 0.05)
    n = {"c": 0}

    async def fake(db, competition, *, live=False, bracket=None):
        n["c"] += 1
        return {"call": n["c"]}

    monkeypatch.setattr(sb, "compute_scoreboard", fake)
    await sb.cached_scoreboard(None, _comp())
    await asyncio.sleep(0.07)
    await sb.cached_scoreboard(None, _comp())
    assert n["c"] == 2


async def test_live_and_bracket_are_separate_keys(monkeypatch):
    n = {"c": 0}

    async def fake(db, competition, *, live=False, bracket=None):
        n["c"] += 1
        return {"live": live, "bracket": bracket}

    monkeypatch.setattr(sb, "compute_scoreboard", fake)
    await sb.cached_scoreboard(None, _comp())  # (False, None)
    await sb.cached_scoreboard(None, _comp(), live=True)  # (True, None)
    await sb.cached_scoreboard(None, _comp(), bracket="A")  # (False, "A")
    await sb.cached_scoreboard(None, _comp())  # hit on (False, None)
    assert n["c"] == 3


async def test_invalidate_clears_all_variants(monkeypatch):
    n = {"c": 0}

    async def fake(db, competition, *, live=False, bracket=None):
        n["c"] += 1
        return {"n": n["c"]}

    monkeypatch.setattr(sb, "compute_scoreboard", fake)
    await sb.cached_scoreboard(None, _comp())  # (False, None)
    await sb.cached_scoreboard(None, _comp(), live=True)  # (True, None)
    assert n["c"] == 2
    sb.invalidate_scoreboard("c1")  # a freeze toggle clears both live + frozen
    await sb.cached_scoreboard(None, _comp())
    await sb.cached_scoreboard(None, _comp(), live=True)
    assert n["c"] == 4
