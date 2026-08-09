"""Request-body size limit (#3): an oversized body is refused before the app
buffers/parses it, so it can't amplify into heap ahead of route auth."""

from utils.body_limit import BodySizeLimitMiddleware


async def test_rejects_oversized_content_length():
    app_called = False

    async def app(scope, receive, send):
        nonlocal app_called
        app_called = True

    mw = BodySizeLimitMiddleware(app, max_bytes=100)
    scope = {"type": "http", "headers": [(b"content-length", b"500")]}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await mw(scope, receive, send)
    assert app_called is False, "app ran despite an over-cap Content-Length"
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


async def test_allows_body_within_cap():
    app_called = False

    async def app(scope, receive, send):
        nonlocal app_called
        app_called = True

    mw = BodySizeLimitMiddleware(app, max_bytes=100)
    scope = {"type": "http", "headers": [(b"content-length", b"50")]}

    async def receive():
        return {"type": "http.request", "body": b"x" * 50, "more_body": False}

    async def send(message):
        pass

    await mw(scope, receive, send)
    assert app_called is True


async def test_streaming_body_cut_off_past_cap():
    """No Content-Length: the wrapped receive stops the stream past the cap so it
    can't buffer without bound."""
    seen = []

    async def app(scope, receive, send):
        while True:
            message = await receive()
            seen.append(message["type"])
            if message["type"] == "http.disconnect" or not message.get("more_body"):
                break

    mw = BodySizeLimitMiddleware(app, max_bytes=100)
    scope = {"type": "http", "headers": []}
    chunks = [
        {"type": "http.request", "body": b"x" * 80, "more_body": True},
        {"type": "http.request", "body": b"x" * 80, "more_body": True},  # crosses cap
    ]

    async def receive():
        return chunks.pop(0)

    async def send(message):
        pass

    await mw(scope, receive, send)
    assert "http.disconnect" in seen
