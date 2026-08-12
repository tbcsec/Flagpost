"""Cross-worker presence membership (#189 Phase 2, ADR-0026).

Models N workers as N ConnectionManagers sharing one in-process presence store
(a deterministic stand-in for RedisPresenceStore, same contract) and one fake
broadcast bus (Phase 1 relay). Asserts the "who's here" list is the global,
deduped union — and that a member survives while *any* worker holds them and
drops only when the last one does. Time is injectable so TTL expiry is
deterministic; no Redis server needed.
"""

import json

from realtime.manager import ConnectionManager
from realtime.relay import RealtimeRelay
from tests.test_realtime_relay import FakeBus, FakeRelay, Sock


class FakeSharedStore:
    """In-process twin of RedisPresenceStore, shared by several managers. Same
    hash + liveness-ZSET semantics, so the manager exercises the real contract:
    a user is present iff some worker holds a non-expired liveness entry."""

    def __init__(self, clock) -> None:
        self._now = clock
        self.hash: dict[tuple[str, str], dict[str, str]] = {}
        self.live: dict[tuple[str, str], dict[str, float]] = {}

    def _for(self, worker_id: str):
        store = self

        class _Bound:
            async def add(self, rt, rid, uid, member):
                store.hash.setdefault((rt, rid), {})[uid] = json.dumps(member)
                store.live.setdefault((rt, rid), {})[f"{uid}|{worker_id}"] = (
                    store._now() + 30
                )

            async def refresh_many(self, entries):
                for rt, rid, uid in entries:
                    store.live.setdefault((rt, rid), {})[f"{uid}|{worker_id}"] = (
                        store._now() + 30
                    )

            async def remove(self, rt, rid, uid):
                store.live.get((rt, rid), {}).pop(f"{uid}|{worker_id}", None)
                store._prune(rt, rid)
                if not any(
                    t.split("|", 1)[0] == uid for t in store.live.get((rt, rid), {})
                ):
                    store.hash.get((rt, rid), {}).pop(uid, None)

            async def members(self, rt, rid):
                store._prune(rt, rid)
                live_uids = {
                    t.split("|", 1)[0] for t in store.live.get((rt, rid), {})
                }
                out = [
                    json.loads(v)
                    for uid, v in store.hash.get((rt, rid), {}).items()
                    if uid in live_uids
                ]
                out.sort(key=lambda m: m.get("name", ""))
                return out

            async def close(self):
                pass

        return _Bound()

    def _prune(self, rt, rid):
        now = self._now()
        live = self.live.get((rt, rid), {})
        for tag in [t for t, exp in live.items() if exp <= now]:
            del live[tag]


def _member(uid, name, role="Participant", mode="view"):
    return {"id": uid, "name": name, "role": role, "mode": mode}


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _last_presence(sock: Sock):
    frames = [f for f in sock.frames if f.get("type") == "presence"]
    return frames[-1]["members"] if frames else None


async def _worker(bus, shared, clock):
    mgr = ConnectionManager()
    mgr.attach_relay(FakeRelay(bus))
    await mgr.start_relay()
    mgr.attach_presence_store(shared._for(mgr.worker_id))
    return mgr


async def test_presence_is_the_global_union_across_workers():
    bus, clock = FakeBus(), Clock()
    shared = FakeSharedStore(clock)
    w1 = await _worker(bus, shared, clock)
    w2 = await _worker(bus, shared, clock)

    # Ada joins on worker 1, Ben on worker 2, same room. A watcher on worker 1
    # must see BOTH — the fragmentation bug this phase fixes.
    watcher = Sock()
    w1.join("challenge", "c1", watcher, "u-watch")
    await w1.presence_join("challenge", "c1", watcher, _member("u-watch", "Watcher"))

    ada = Sock()
    w1.join("challenge", "c1", ada, "u-ada")
    await w1.presence_join("challenge", "c1", ada, _member("u-ada", "Ada"))

    ben = Sock()
    w2.join("challenge", "c1", ben, "u-ben")
    await w2.presence_join("challenge", "c1", ben, _member("u-ben", "Ben"))

    names = [m["name"] for m in _last_presence(watcher)]
    assert names == ["Ada", "Ben", "Watcher"]  # union, sorted, deduped


async def test_member_survives_while_another_worker_holds_them():
    bus, clock = FakeBus(), Clock()
    shared = FakeSharedStore(clock)
    w1 = await _worker(bus, shared, clock)
    w2 = await _worker(bus, shared, clock)

    # Same user on two workers (two devices). Dropping the worker-1 socket must
    # NOT remove them — worker 2 still holds them.
    a1, a2 = Sock(), Sock()
    w1.join("challenge", "c1", a1, "u-a")
    await w1.presence_join("challenge", "c1", a1, _member("u-a", "Ada"))
    w2.join("challenge", "c1", a2, "u-a")
    await w2.presence_join("challenge", "c1", a2, _member("u-a", "Ada"))

    await w1.presence_leave("challenge", "c1", a1, "u-a", grace_seconds=0.0)
    # Give the debounced expiry a tick to run.
    import asyncio

    await asyncio.sleep(0.05)

    members = await shared._for(w2.worker_id).members("challenge", "c1")
    assert [m["id"] for m in members] == ["u-a"]  # still present via worker 2


async def test_dead_worker_members_age_out_of_the_union():
    bus, clock = FakeBus(), Clock()
    shared = FakeSharedStore(clock)
    w1 = await _worker(bus, shared, clock)
    w2 = await _worker(bus, shared, clock)

    # Ada on w1, Ben on w2. w2 "crashes": it stops heartbeating (we just never
    # refresh). After the TTL, Ben must fall out of the computed membership.
    ada = Sock()
    w1.join("challenge", "c1", ada, "u-ada")
    await w1.presence_join("challenge", "c1", ada, _member("u-ada", "Ada"))
    ben = Sock()
    w2.join("challenge", "c1", ben, "u-ben")
    await w2.presence_join("challenge", "c1", ben, _member("u-ben", "Ben"))

    assert {m["id"] for m in await shared._for(w1.worker_id).members("challenge", "c1")} == {
        "u-ada",
        "u-ben",
    }

    clock.t += 31  # advance past the 30s liveness TTL
    # The LIVE worker heartbeats its members (what _presence_heartbeat does);
    # the crashed worker doesn't, so only Ben's liveness ages out.
    await shared._for(w1.worker_id).refresh_many([("challenge", "c1", "u-ada")])
    survivors = await shared._for(w1.worker_id).members("challenge", "c1")
    assert [m["id"] for m in survivors] == ["u-ada"]  # dead worker's member gone


async def test_single_worker_presence_is_unchanged_without_a_store():
    # No store attached ⇒ today's purely in-process behaviour.
    mgr = ConnectionManager()
    sock = Sock()
    mgr.join("challenge", "c1", sock, "u-a")
    await mgr.presence_join("challenge", "c1", sock, _member("u-a", "Ada"))
    assert mgr.presence_members("challenge", "c1") == [_member("u-a", "Ada")]
    assert _last_presence(sock) == [_member("u-a", "Ada")]
