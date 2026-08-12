"""Cross-worker broadcast relay (#189, ADR-0025).

Models N uvicorn workers as N ConnectionManager instances wired to one shared
in-process bus (a stand-in for Redis pub/sub — like a Redis publish, a payload
reaches *every* subscribed worker, including the publisher, so the origin-skip
logic is actually exercised). No Redis server needed.
"""

from realtime.manager import ConnectionManager
from realtime.relay import RealtimeRelay


class FakeBus:
    """One shared pub/sub fabric several FakeRelays attach to."""

    def __init__(self) -> None:
        self.handlers: list = []

    async def publish(self, payload: dict) -> None:
        # Fan out to every subscriber, publisher included — exactly what Redis
        # pub/sub does, so the manager's own-origin skip must handle it.
        for handler in list(self.handlers):
            await handler(payload)


class FakeRelay(RealtimeRelay):
    def __init__(self, bus: FakeBus) -> None:
        self._bus = bus
        self._handler = None

    async def publish(self, payload: dict) -> None:
        await self._bus.publish(payload)

    async def start(self, handler) -> None:
        self._handler = handler
        self._bus.handlers.append(handler)

    async def stop(self) -> None:
        if self._handler in self._bus.handlers:
            self._bus.handlers.remove(self._handler)


class Sock:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.frames.append(message)


async def _wire(bus: FakeBus, mgr: ConnectionManager) -> None:
    mgr.attach_relay(FakeRelay(bus))
    await mgr.start_relay()


async def test_broadcast_reaches_a_socket_on_another_worker():
    bus = FakeBus()
    w1, w2 = ConnectionManager(), ConnectionManager()
    await _wire(bus, w1)
    await _wire(bus, w2)

    # A client is connected to worker 2; the solve is broadcast on worker 1.
    remote = Sock()
    w2.join("scoreboard", "c1", remote, "u-remote")
    await w1.broadcast("scoreboard", "c1", {"type": "scoreboard"})

    assert remote.frames == [{"type": "scoreboard"}]


async def test_origin_worker_delivers_exactly_once():
    # The publisher also receives its own relayed frame (Redis fans to all); the
    # manager must skip it, or the emitting worker's clients get every frame
    # twice.
    bus = FakeBus()
    w1, w2 = ConnectionManager(), ConnectionManager()
    await _wire(bus, w1)
    await _wire(bus, w2)

    local = Sock()
    w1.join("scoreboard", "c1", local, "u-local")
    await w1.broadcast("scoreboard", "c1", {"n": 1})

    assert local.frames == [{"n": 1}]  # once, not twice


async def test_every_worker_delivers_to_its_own_locals():
    bus = FakeBus()
    w1, w2 = ConnectionManager(), ConnectionManager()
    await _wire(bus, w1)
    await _wire(bus, w2)

    on1, on2 = Sock(), Sock()
    w1.join("activity", "c1", on1, "u1")
    w2.join("activity", "c1", on2, "u2")
    await w2.broadcast("activity", "c1", {"event": "challenge.solved"})

    assert on1.frames == [{"event": "challenge.solved"}]
    assert on2.frames == [{"event": "challenge.solved"}]


async def test_exclude_stays_local_and_does_not_cross_the_relay():
    # The CRDT sender is excluded on its own worker; a same-room client on
    # another worker still receives the update (it isn't the sender).
    bus = FakeBus()
    w1, w2 = ConnectionManager(), ConnectionManager()
    await _wire(bus, w1)
    await _wire(bus, w2)

    sender = Sock()
    peer_same_worker = Sock()
    peer_other_worker = Sock()
    w1.join("note", "d1", sender, "u-sender")
    w1.join("note", "d1", peer_same_worker, "u-peer1")
    w2.join("note", "d1", peer_other_worker, "u-peer2")

    await w1.broadcast("note", "d1", {"crdt": True}, exclude=sender)

    assert sender.frames == []                     # excluded on its own worker
    assert peer_same_worker.frames == [{"crdt": True}]
    assert peer_other_worker.frames == [{"crdt": True}]  # relayed, not excluded


async def test_single_worker_without_relay_is_pure_local():
    # No relay attached ⇒ today's behaviour: local delivery, no publish path.
    mgr = ConnectionManager()
    s = Sock()
    mgr.join("scoreboard", "c1", s, "u1")
    await mgr.broadcast("scoreboard", "c1", {"x": 1})
    await mgr.stop_relay()  # safe no-op with no relay attached
    assert s.frames == [{"x": 1}]
