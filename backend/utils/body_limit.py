"""ASGI request-body size limit (#3).

Starlette buffers and (for JSON) decodes the whole request body before a route's
auth dependency runs, so an oversized body — e.g. to POST /api/site-settings/import,
whose payload is an opaque dict — amplifies into transient heap before the
401/403, an unauthenticated memory-DoS. This middleware rejects a request whose
declared Content-Length exceeds the cap with 413 *before* the app reads it, and
truncates a chunked / unknown-length body once it crosses the cap so it can't
buffer without bound. The per-route upload guards (utils.uploads) already bound
the multipart file routes; this backstops every JSON endpoint.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Fast path: an honest Content-Length over the cap is refused up front,
        # before a single body byte is read (covers the JSON-POST vector).
        for name, value in scope.get("headers", ()):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                if declared is not None and declared > self.max_bytes:
                    await self._reject(send)
                    return
                break

        # Slow path: no/again untrusted Content-Length — count streamed bytes and
        # cut the stream off past the cap so nothing buffers without bound.
        total = 0

        async def limited_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, limited_receive, send)

    @staticmethod
    async def _reject(send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"detail":"Request body too large"}',
            }
        )
