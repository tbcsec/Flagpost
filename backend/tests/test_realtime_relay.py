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

    async def start(self, handler, *, on_gap=None) -> None:
        self.on_gap = on_gap
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


# --- eviction across workers (GHSA-p679) -------------------------------------


class ClosableSock(Sock):
    """A socket whose close is recorded — or, with ``hang=True``, never returns,
    standing in for a half-open TCP peer."""

    def __init__(self, *, hang: bool = False) -> None:
        super().__init__()
        self.closed_code: int | None = None
        self._hang = hang

    async def close(self, code: int = 1000) -> None:
        import asyncio

        if self._hang:
            await asyncio.Event().wait()
        self.closed_code = code


async def test_eviction_reaches_a_socket_on_another_worker():
    """The core finding: revocation ran only on the worker that emitted the
    event, so a socket held on any other worker survived it indefinitely."""
    bus = FakeBus()
    w1, w2 = ConnectionManager(), ConnectionManager()
    await _wire(bus, w1)
    await _wire(bus, w2)

    remote = ClosableSock()
    w2.join("ticket", "t-internal", remote, "demoted-judge")

    await w1.close_user_sockets("demoted-judge")  # the request landed on w1

    assert remote.closed_code == 4403
    assert w2.is_revoked(remote)


async def test_eviction_filters_survive_the_relay():
    # A team removal targets only that team's scratchpads; the filter has to
    # apply on the remote worker too, not widen into a full eviction.
    bus = FakeBus()
    w1, w2 = ConnectionManager(), ConnectionManager()
    await _wire(bus, w1)
    await _wire(bus, w2)

    old_team, other_team, board = ClosableSock(), ClosableSock(), ClosableSock()
    w2.join("note", "team_challenge:t1:c", old_team, "alice")
    w2.join("note", "team_challenge:t2:c", other_team, "alice")
    w2.join("scoreboard", "comp", board, "alice")

    await w1.close_user_sockets(
        "alice", room_type="note", room_id_prefix="team_challenge:t1:"
    )

    assert old_team.closed_code == 4403
    assert other_team.closed_code is None and board.closed_code is None
    assert not w2.is_revoked(other_team) and not w2.is_revoked(board)


async def test_revoked_socket_gets_nothing_even_if_its_close_stalls(monkeypatch):
    """A close that never completes must not leave the socket receiving. It is
    revoked before the close is attempted, and delivery skips revoked sockets."""
    from config import settings

    monkeypatch.setattr(settings, "ws_send_timeout_seconds", 0.05)
    bus = FakeBus()
    w1, w2 = ConnectionManager(), ConnectionManager()
    await _wire(bus, w1)
    await _wire(bus, w2)

    stuck = ClosableSock(hang=True)
    w2.join("ticket", "t-internal", stuck, "banned")

    import asyncio

    # Bounded: a regression in the close bound fails here instead of hanging.
    await asyncio.wait_for(w1.close_user_sockets("banned"), timeout=5.0)
    assert stuck.closed_code is None  # the TCP close never finished...
    assert w2.is_revoked(stuck)  # ...but access is gone regardless

    await w1.broadcast("ticket", "t-internal", {"type": "internal_note"})
    assert stuck.frames == []


async def test_eviction_is_effective_even_if_the_handler_is_cancelled():
    """The event bus cancels background handlers at their timeout. Marking
    happens before the first await, so cancelling the eviction part-way — here,
    while the relay publish is in flight — cannot leave a local socket live."""
    import asyncio

    class _HangingRelay(FakeRelay):
        async def publish(self, payload: dict) -> None:
            await asyncio.Event().wait()

    w1 = ConnectionManager()
    w1.attach_relay(_HangingRelay(FakeBus()))
    local = ClosableSock()
    w1.join("note", "team_challenge:t1:c", local, "removed")

    task = asyncio.ensure_future(w1.close_user_sockets("removed"))
    await asyncio.sleep(0)  # let it run up to the hanging publish
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert w1.is_revoked(local)
    await w1._deliver_local("note", "team_challenge:t1:c", {"type": "note_update"})
    assert local.frames == []


async def test_leave_clears_the_revoked_mark():
    # The set must not grow forever: once the socket's receive loop unwinds and
    # leaves, the mark goes with it.
    w = ConnectionManager()
    ws = ClosableSock()
    w.join("scoreboard", "c1", ws, "u")
    await w.close_user_sockets("u")
    assert w.is_revoked(ws)
    w.leave("scoreboard", "c1", ws)
    assert not w.is_revoked(ws)


# --- relay supervision + eviction hardening (GHSA-p679 review) ---------------


class _FakePubSub:
    """One pub/sub connection: yields ``messages`` then either drops (raises,
    like a Redis restart) or idles until cancelled."""

    def __init__(self, messages, *, drop: bool) -> None:
        self._messages = messages
        self._drop = drop

    async def subscribe(self, channel) -> None:
        return None

    async def listen(self):
        import asyncio

        for m in self._messages:
            yield {"type": "message", "data": m}
        if self._drop:
            raise ConnectionError("Connection closed by server.")
        await asyncio.Event().wait()

    async def unsubscribe(self, channel) -> None:
        return None

    async def aclose(self) -> None:
        return None


class _FakeRedis:
    def __init__(self, pubsubs) -> None:
        self._pubsubs = list(pubsubs)

    def pubsub(self):
        return self._pubsubs.pop(0)

    async def aclose(self) -> None:
        return None


async def test_relay_resubscribes_after_a_dropped_connection(monkeypatch):
    """The subscriber used to log and *return* on a dropped Redis connection,
    and nothing restarted it: the worker silently stopped hearing its peers —
    including their evictions — until it was restarted. It must resubscribe,
    keep delivering, and report the gap."""
    import asyncio
    import json

    import realtime.relay as relay_mod

    monkeypatch.setattr(relay_mod, "_RESUBSCRIBE_INITIAL_S", 0.01)
    relay = relay_mod.RedisRelay("redis://127.0.0.1:1/0")  # never connects
    relay._redis = _FakeRedis([
        _FakePubSub([json.dumps({"n": 1})], drop=True),  # Redis restarts...
        _FakePubSub([json.dumps({"n": 2})], drop=False),  # ...and comes back
    ])

    got: list[dict] = []
    gaps: list[int] = []
    second = asyncio.Event()

    async def handler(payload):
        got.append(payload)
        if payload["n"] == 2:
            second.set()

    async def on_gap():
        gaps.append(1)

    await relay.start(handler, on_gap=on_gap)
    try:
        await asyncio.wait_for(second.wait(), timeout=5.0)
    finally:
        await relay.stop()

    assert got == [{"n": 1}, {"n": 2}]  # delivery resumed after the drop
    assert gaps == [1]  # and the gap was reported exactly once


async def test_relay_gap_closes_and_revokes_every_local_socket():
    """Pub/sub is at-most-once: evictions published during the gap are gone, and
    this worker can't know whose access changed. So every local socket is made
    inert and closed; clients reconnect and re-handshake against current state."""
    import asyncio

    bus = FakeBus()
    w = ConnectionManager()
    relay = FakeRelay(bus)
    w.attach_relay(relay)
    await w.start_relay()

    a, b = ClosableSock(), ClosableSock()
    w.join("ticket", "t1", a, "u1")
    w.join("scoreboard", "c1", b, "u2")
    before = w.revocation_epoch("u1")

    await relay.on_gap()
    await asyncio.wait_for(asyncio.gather(*w._background), timeout=5.0)

    assert a.closed_code == 1012 and b.closed_code == 1012
    assert w.is_revoked(a) and w.is_revoked(b)
    # An in-flight handshake for anyone is invalidated too.
    assert w.revocation_epoch("u1") != before


async def test_failed_publish_still_closes_local_sockets():
    """Publish and local close used to be sequential, so a Redis error on the
    publish skipped the local closes entirely."""
    import asyncio

    class _BrokenRelay(FakeRelay):
        async def publish(self, payload: dict) -> None:
            raise ConnectionError("redis down")

    w = ConnectionManager()
    w.attach_relay(_BrokenRelay(FakeBus()))
    ws = ClosableSock()
    w.join("ticket", "t1", ws, "banned")

    await asyncio.wait_for(w.close_user_sockets("banned"), timeout=5.0)

    assert ws.closed_code == 4403
    assert w.is_revoked(ws)


async def test_relayed_eviction_does_not_block_the_subscriber(monkeypatch):
    """_on_relayed runs inside a worker's single subscriber task. Awaiting a
    stalled peer's close there held up every other relayed frame behind it.
    It must mark inline and close in the background."""
    import asyncio

    from config import settings

    monkeypatch.setattr(settings, "ws_send_timeout_seconds", 5.0)
    w = ConnectionManager()
    stuck = ClosableSock(hang=True)
    w.join("ticket", "t1", stuck, "banned")

    # Returns well inside the 5s close bound: the close was not awaited here.
    await asyncio.wait_for(
        w._on_relayed(
            {"origin": "other-worker", "kind": "evict", "user_ids": ["banned"],
             "room_type": None, "room_id_prefix": None, "code": 4403}
        ),
        timeout=1.0,
    )
    assert w.is_revoked(stuck)
    for task in list(w._background):
        task.cancel()


async def test_a_dropped_socket_is_closed_not_just_forgotten(monkeypatch):
    """A broadcast send that timed out used to drop the socket from the indexes
    without closing it — leaving a live connection eviction could no longer
    find (a "ghost"). It must actually be closed."""
    import asyncio

    from config import settings

    monkeypatch.setattr(settings, "ws_send_timeout_seconds", 0.05)

    class _StallsOnSend(ClosableSock):
        async def send_json(self, message: dict) -> None:
            await asyncio.Event().wait()

    w = ConnectionManager()
    slow = _StallsOnSend()
    w.join("note", "team_challenge:t1:c", slow, "attacker")

    await asyncio.wait_for(
        w.broadcast("note", "team_challenge:t1:c", {"type": "note_update"}),
        timeout=5.0,
    )
    await asyncio.wait_for(asyncio.gather(*w._background), timeout=5.0)

    assert not w.may_serve(slow)  # untracked: the router refuses its frames
    assert slow.closed_code == 1013  # and it was told to go
