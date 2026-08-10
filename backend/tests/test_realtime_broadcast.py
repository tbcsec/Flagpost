"""Room broadcast is parallel and per-send timeout-bounded (#177).

The old sequential loop let one slow client (a full TCP send buffer on a
congested link) stall delivery to the whole room. Broadcast now fans out
concurrently, each send bounded by ``ws_send_timeout_seconds``; a socket that
times out or errors is reaped like any dead one.
"""

import asyncio

from config import settings
from realtime.manager import ConnectionManager


class Good:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.frames.append(message)


class Boom:
    async def send_json(self, message: dict) -> None:
        raise RuntimeError("client vanished")


class Slow:
    """Never returns from a send within any sane timeout (stalled buffer)."""

    def __init__(self) -> None:
        self.started = False

    async def send_json(self, message: dict) -> None:
        self.started = True
        await asyncio.sleep(3600)


async def test_broadcast_delivers_to_every_socket():
    mgr = ConnectionManager()
    a, b = Good(), Good()
    mgr.join("scoreboard", "c1", a, "u-a")
    mgr.join("scoreboard", "c1", b, "u-b")
    await mgr.broadcast("scoreboard", "c1", {"type": "scoreboard"})
    assert a.frames == [{"type": "scoreboard"}]
    assert b.frames == [{"type": "scoreboard"}]


async def test_failing_socket_is_reaped_without_dropping_neighbours():
    mgr = ConnectionManager()
    good, boom = Good(), Boom()
    mgr.join("scoreboard", "c1", boom, "u-boom")
    mgr.join("scoreboard", "c1", good, "u-good")
    await mgr.broadcast("scoreboard", "c1", {"x": 1})
    assert good.frames == [{"x": 1}]
    assert mgr.room_size("scoreboard", "c1") == 1  # boom dropped


async def test_slow_socket_times_out_without_stalling_the_room(monkeypatch):
    monkeypatch.setattr(settings, "ws_send_timeout_seconds", 0.1)
    mgr = ConnectionManager()
    good, slow = Good(), Slow()
    mgr.join("scoreboard", "c1", slow, "u-slow")
    mgr.join("scoreboard", "c1", good, "u-good")

    loop = asyncio.get_event_loop()
    t0 = loop.time()
    await asyncio.wait_for(mgr.broadcast("scoreboard", "c1", {"x": 1}), timeout=2.0)
    elapsed = loop.time() - t0

    assert good.frames == [{"x": 1}]          # fast client not held hostage
    assert slow.started is True               # the slow send was attempted
    assert elapsed < 1.5                       # bounded by the 0.1s send timeout, not 3600s
    assert mgr.room_size("scoreboard", "c1") == 1  # slow socket reaped


async def test_exclude_still_skips_the_sender():
    mgr = ConnectionManager()
    sender, other = Good(), Good()
    mgr.join("challenge", "c1", sender, "u-s")
    mgr.join("challenge", "c1", other, "u-o")
    await mgr.broadcast("challenge", "c1", {"crdt": True}, exclude=sender)
    assert sender.frames == []
    assert other.frames == [{"crdt": True}]
