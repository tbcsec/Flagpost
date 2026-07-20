"""Minimal async ASGI WebSocket driver for tests (ADR-0006).

httpx's ASGITransport speaks HTTP only, and Starlette's sync TestClient can't
run inside the suite's asyncio loop — so this drives the app's websocket scope
directly: two queues stand in for the transport, and the app runs as a task on
the same loop (and the same file-backed SQLite) as the rest of the suite.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


class WsTestClient:
    def __init__(self, app, path: str) -> None:
        self._app = app
        self._path = path
        self._to_app: asyncio.Queue[dict] = asyncio.Queue()
        self._from_app: asyncio.Queue[dict] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> "WsTestClient":
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "path": self._path,
            "raw_path": self._path.encode(),
            "root_path": "",
            "scheme": "ws",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "subprotocols": [],
        }
        self._task = asyncio.ensure_future(
            self._app(scope, self._to_app.get, self._from_app.put)
        )
        await self._to_app.put({"type": "websocket.connect"})
        accepted = await self.next_message()
        assert accepted["type"] == "websocket.accept", accepted
        return self

    async def __aexit__(self, *exc) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                self._task.cancel()

    async def next_message(self, timeout: float = 5.0) -> dict:
        """The next raw ASGI message from the app (send/close frames)."""
        return await asyncio.wait_for(self._from_app.get(), timeout)

    async def send_json(self, data: Any) -> None:
        await self._to_app.put(
            {"type": "websocket.receive", "text": json.dumps(data)}
        )

    async def receive_json(self, timeout: float = 5.0) -> Any:
        message = await self.next_message(timeout)
        assert message["type"] == "websocket.send", message
        return json.loads(message["text"])

    async def expect_close(self, timeout: float = 5.0) -> int:
        """Assert the server closes the socket; return the close code."""
        message = await self.next_message(timeout)
        assert message["type"] == "websocket.close", message
        return message.get("code", 1000)
