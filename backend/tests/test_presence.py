"""Presence tracking on the connection manager (§4.1), exercised directly with
fake sockets so join/leave, per-user dedup across tabs, and the *debounced*
clear are deterministic without standing up a real WebSocket."""

from __future__ import annotations

import asyncio

from realtime.manager import ConnectionManager


class FakeSocket:
    """Stands in for a Starlette WebSocket: records the frames it's sent."""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.frames.append(message)

    def presence_sets(self) -> list[list[str]]:
        """The member-id lists from every presence frame this socket received."""
        return [
            [m["id"] for m in f["members"]]
            for f in self.frames
            if f.get("type") == "presence"
        ]


def _member(uid: str, name: str, role: str = "participant", mode: str = "view") -> dict:
    return {"id": uid, "name": name, "role": role, "mode": mode}


async def test_presence_join_broadcasts_sorted_set() -> None:
    mgr = ConnectionManager()
    a, b = FakeSocket(), FakeSocket()

    mgr.join("challenge", "c1", a, "u-a")
    await mgr.presence_join("challenge", "c1", a, _member("u-a", "Zara"))

    mgr.join("challenge", "c1", b, "u-b")
    await mgr.presence_join("challenge", "c1", b, _member("u-b", "Ada"))

    # Both sockets are in the room, so both see the final set — ordered by name.
    assert mgr.presence_members("challenge", "c1") == [
        _member("u-b", "Ada"),
        _member("u-a", "Zara"),
    ]
    assert a.presence_sets()[-1] == ["u-b", "u-a"]
    assert b.presence_sets()[-1] == ["u-b", "u-a"]


async def test_presence_payload_shape_is_the_minimal_set() -> None:
    mgr = ConnectionManager()
    a = FakeSocket()
    mgr.join("ticket", "t1", a, "u-a")
    await mgr.presence_join(
        "ticket", "t1", a, _member("u-a", "Judge", role="staff", mode="edit")
    )
    (payload,) = mgr.presence_members("ticket", "t1")
    assert payload == {"id": "u-a", "name": "Judge", "role": "staff", "mode": "edit"}


async def test_multiple_tabs_dedupe_and_survive_one_closing() -> None:
    mgr = ConnectionManager()
    tab1, tab2 = FakeSocket(), FakeSocket()
    mgr.join("challenge", "c1", tab1, "u-a")
    await mgr.presence_join("challenge", "c1", tab1, _member("u-a", "Ada"))
    mgr.join("challenge", "c1", tab2, "u-a")
    await mgr.presence_join("challenge", "c1", tab2, _member("u-a", "Ada"))

    # One user, not two.
    assert mgr.presence_members("challenge", "c1") == [_member("u-a", "Ada")]

    # Closing one tab must not schedule a clear — the other tab keeps them here.
    await mgr.presence_leave("challenge", "c1", tab1, "u-a", grace_seconds=0.01)
    await asyncio.sleep(0.05)
    assert mgr.presence_members("challenge", "c1") == [_member("u-a", "Ada")]


async def test_presence_clear_is_debounced() -> None:
    mgr = ConnectionManager()
    watcher, leaver = FakeSocket(), FakeSocket()
    mgr.join("challenge", "c1", watcher, "u-w")
    await mgr.presence_join("challenge", "c1", watcher, _member("u-w", "Watcher"))
    mgr.join("challenge", "c1", leaver, "u-l")
    await mgr.presence_join("challenge", "c1", leaver, _member("u-l", "Leaver"))

    # The socket dropped, but leave() removes it from the room too (as the real
    # endpoint does), so only the watcher sees the eventual clear frame.
    mgr.leave("challenge", "c1", leaver)
    await mgr.presence_leave("challenge", "c1", leaver, "u-l", grace_seconds=0.05)

    # Not cleared instantly — still present right after leaving.
    assert [m["id"] for m in mgr.presence_members("challenge", "c1")] == ["u-l", "u-w"]

    await asyncio.sleep(0.12)
    assert [m["id"] for m in mgr.presence_members("challenge", "c1")] == ["u-w"]
    assert watcher.presence_sets()[-1] == ["u-w"]


async def test_reconnect_within_grace_cancels_the_clear() -> None:
    mgr = ConnectionManager()
    sock = FakeSocket()
    mgr.join("challenge", "c1", sock, "u-a")
    await mgr.presence_join("challenge", "c1", sock, _member("u-a", "Ada"))

    # Drop, then reconnect a new socket before the grace window elapses.
    mgr.leave("challenge", "c1", sock)
    await mgr.presence_leave("challenge", "c1", sock, "u-a", grace_seconds=0.1)
    reconnect = FakeSocket()
    mgr.join("challenge", "c1", reconnect, "u-a")
    await mgr.presence_join("challenge", "c1", reconnect, _member("u-a", "Ada"))

    # Wait past the original grace — the pending clear must have been cancelled.
    await asyncio.sleep(0.15)
    assert mgr.presence_members("challenge", "c1") == [_member("u-a", "Ada")]
