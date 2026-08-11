"""Per-key leading+trailing coalescer (#175)."""

import asyncio

from utils.coalesce import Coalescer


def _recorder(delivered: bool = True):
    calls: list[tuple] = []

    async def send(key, value):
        calls.append((key, value))
        return delivered

    return calls, send


async def test_leading_edge_fires_immediately():
    calls, send = _recorder()
    c = Coalescer(0.05, send)
    await c.hit("x", "a")
    assert calls == [("x", "a")]


async def test_burst_collapses_to_leading_plus_one_trailing_with_latest():
    calls, send = _recorder()
    c = Coalescer(0.05, send)
    await c.hit("x", "1")
    await c.hit("x", "2")
    await c.hit("x", "3")
    assert calls == [("x", "1")]  # only the leading edge so far
    await asyncio.sleep(0.08)  # window closes → one trailing with the latest value
    assert calls == [("x", "1"), ("x", "3")]


async def test_distinct_keys_do_not_coalesce():
    calls, send = _recorder()
    c = Coalescer(0.05, send)
    await c.hit("a", 1)
    await c.hit("b", 2)
    assert calls == [("a", 1), ("b", 2)]  # both lead independently


async def test_well_spaced_events_each_lead():
    calls, send = _recorder()
    c = Coalescer(0.02, send)
    await c.hit("x", 1)
    await asyncio.sleep(0.05)  # window fully closes with nothing pending
    await c.hit("x", 2)
    assert calls == [("x", 1), ("x", 2)]


async def test_undelivered_send_is_not_tracked():
    # send reports "not delivered" (e.g. empty room) → the key isn't tracked, so
    # the next hit is a fresh leading edge and no trailing fires for the burst
    # that nobody received. This is the fix for the activity-room silence flake:
    # events while the room is empty don't buffer a ping for a later connector.
    calls, send = _recorder(delivered=False)
    c = Coalescer(0.05, send)
    await c.hit("x", 1)
    await c.hit("x", 2)  # not coalesced — "x" was never tracked
    assert calls == [("x", 1), ("x", 2)]
    await asyncio.sleep(0.08)
    assert calls == [("x", 1), ("x", 2)]  # no trailing


async def test_steady_stream_fires_once_per_window():
    calls, send = _recorder()
    c = Coalescer(0.05, send)
    # 6 hits at ~half-window cadence → leading + a trailing per closed window,
    # never one-per-hit.
    for i in range(6):
        await c.hit("x", i)
        await asyncio.sleep(0.025)
    await asyncio.sleep(0.1)
    assert calls[0] == ("x", 0)  # leading
    assert len(calls) < 6  # coalesced, not one per hit
    assert calls[-1] == ("x", 5)  # last value never lost
