"""Event bus behavioural guarantees (ARCHITECTURE.md §3.1, ADR-0005)."""

import asyncio

from utils.event_bus import EventBus


async def test_exact_and_wildcard_matching():
    bus = EventBus()
    seen: list[str] = []

    @bus.on("challenge.solved")
    async def _exact(name, payload):
        seen.append(f"exact:{name}")

    @bus.on("challenge.*")
    async def _wild(name, payload):
        seen.append(f"wild:{name}")

    @bus.on("*")
    async def _all(name, payload):
        seen.append(f"all:{name}")

    await bus.emit("challenge.solved", {})
    await bus.emit("ticket.created", {})

    assert "exact:challenge.solved" in seen
    assert "wild:challenge.solved" in seen
    assert "all:challenge.solved" in seen
    # exact/wild must NOT fire for a different entity
    assert "exact:ticket.created" not in seen
    assert "wild:ticket.created" not in seen
    assert "all:ticket.created" in seen


async def test_segment_count_must_match():
    bus = EventBus()
    seen: list[str] = []

    @bus.on("challenge.*")
    async def _wild(name, payload):
        seen.append(name)

    # "challenge.*" is a two-segment pattern; a three-segment event must miss.
    await bus.emit("challenge.hint.requested", {})
    await bus.emit("challenge.solved", {})
    assert seen == ["challenge.solved"]


async def test_handler_failure_is_isolated():
    bus = EventBus()
    survived: list[str] = []

    @bus.on("x.y")
    async def _boom(name, payload):
        raise RuntimeError("handler blew up")

    @bus.on("x.y")
    async def _ok(name, payload):
        survived.append(name)

    # A raising handler must not prevent siblings or bubble into emit().
    await bus.emit("x.y", {})
    assert survived == ["x.y"]


async def test_slow_handler_times_out_without_blocking_siblings():
    bus = EventBus(handler_timeout=0.05)
    fast_done: list[str] = []

    @bus.on("x.y")
    async def _hang(name, payload):
        await asyncio.sleep(5)  # would exceed the timeout

    @bus.on("x.y")
    async def _fast(name, payload):
        fast_done.append(name)

    # emit() returns promptly (well under the hung handler's 5s sleep) and the
    # fast handler still ran.
    await asyncio.wait_for(bus.emit("x.y", {}), timeout=1.0)
    assert fast_done == ["x.y"]


async def test_unsubscribe_owner_detaches_handlers():
    bus = EventBus()
    seen: list[str] = []

    @bus.on("x.y", owner="plugin_a")
    async def _h(name, payload):
        seen.append(name)

    await bus.emit("x.y", {})
    bus.unsubscribe_owner("plugin_a")
    await bus.emit("x.y", {})
    assert seen == ["x.y"]  # only the pre-detach emit landed
