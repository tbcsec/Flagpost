"""The shared bounded reader for outbound response bodies (GHSA-r7rp-46pp-x55q).

Bodies are served as async streams, the way a network response arrives, so the
raw-read path runs (an in-memory ``httpx.Response`` is read at construction).
"""

import asyncio
import gzip
import tracemalloc
import zlib

import httpx
import pytest

from utils import http_bounded


class _Body:
    """An async byte stream that records how many chunks the client pulled."""

    def __init__(self, *chunks: bytes):
        self.chunks = chunks
        self.pulled = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.pulled += 1
            yield chunk


def _zeros_gzip(mib: int, *, layers: int = 1) -> bytes:
    data = bytes(mib << 20)
    for _ in range(layers):
        data = gzip.compress(data, 9)
    return data


async def _fetch(response: httpx.Response, max_bytes: int, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await http_bounded.fetch(client, "GET", "https://x.example/", max_bytes=max_bytes)


async def test_asks_for_an_uncompressed_response():
    seen: list[httpx.Request] = []
    await _fetch(httpx.Response(200, content=_Body(b"{}")), 1024, seen)
    assert seen[0].headers["Accept-Encoding"] == "identity"


@pytest.mark.parametrize("coding", ["br", "zstd", "gzip, gzip", "gzip, br", "compress"])
async def test_refuses_codings_it_does_not_decode_without_reading(coding):
    body = _Body(b"\x1b\xff\xff" * 8)
    response = httpx.Response(200, headers={"Content-Encoding": coding}, content=body)
    with pytest.raises(httpx.DecodingError, match="refusing Content-Encoding"):
        await _fetch(response, 1024)
    assert body.pulled == 0


@pytest.mark.parametrize(
    ("coding", "encode"),
    [
        ("gzip", lambda b: gzip.compress(b)),
        ("x-gzip", lambda b: gzip.compress(b)),
        ("deflate", lambda b: zlib.compress(b)),
        ("identity", lambda b: b),
    ],
)
async def test_one_layer_of_a_stored_encoding_is_decoded(coding, encode):
    # A static mirror can serve a stored Content-Encoding whatever was asked.
    doc = b'{"resolved": {"id": "a"}}' * 40
    raw = encode(doc)
    body = _Body(*(raw[i : i + 7] for i in range(0, len(raw), 7)))  # chunked
    response = httpx.Response(200, headers={"Content-Encoding": coding}, content=body)
    _, got = await _fetch(response, 4096)
    assert got == doc


async def test_a_gzip_bomb_stops_at_the_cap_without_expanding():
    bomb = _zeros_gzip(16)  # ~16 KiB on the wire, 16 MiB decoded
    response = httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=_Body(bomb))
    tracemalloc.start()
    try:
        with pytest.raises(http_bounded.BodyTooLarge):
            await _fetch(response, 4096)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # Decoding stopped one byte past the cap, not at the 16 MiB on offer.
    assert peak < 2 << 20


async def test_an_endless_uncompressed_body_is_cut_off_at_the_cap():
    body = _Body(*([b"x" * 1024] * 10_000))
    with pytest.raises(http_bounded.BodyTooLarge):
        await _fetch(httpx.Response(200, content=body), 4096)
    assert body.pulled == 5


async def test_a_declared_length_over_the_cap_is_refused_unread():
    body = _Body(b"x" * 8192)
    response = httpx.Response(200, headers={"Content-Length": "8192"}, content=body)
    with pytest.raises(http_bounded.BodyTooLarge):
        await _fetch(response, 4096)
    assert body.pulled == 0


async def test_a_body_exactly_at_the_cap_is_returned():
    _, got = await _fetch(httpx.Response(200, content=_Body(b"ab", b"cd")), 4)
    assert got == b"abcd"


async def test_an_error_status_returns_without_reading_the_body():
    body = _Body(*([b"x" * 1024] * 100))
    response, got = await _fetch(httpx.Response(503, content=body), 16)
    assert (response.status_code, got, body.pulled) == (503, b"", 0)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"not gzip at all", "malformed"),
        (gzip.compress(b"{}") + gzip.compress(b"{}"), "after the end"),
        (gzip.compress(b'{"a": 1}' * 50)[:-12], "truncated"),
    ],
    ids=["garbage", "trailing-member", "truncated"],
)
async def test_a_malformed_gzip_body_is_a_decoding_error(raw, message):
    response = httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=_Body(raw))
    with pytest.raises(httpx.DecodingError, match=message):
        await _fetch(response, 4096)


async def test_a_stacked_gzip_bomb_off_the_wire_is_refused_without_expanding():
    # A real server on loopback, so the network read path runs end to end: two
    # gzip layers, a few hundred bytes on the wire, 64 MiB decoded.
    bomb = _zeros_gzip(64, layers=2)
    writers: list[asyncio.StreamWriter] = []

    async def _serve(reader, writer):
        writers.append(writer)
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip, gzip\r\n"
            b"Content-Length: " + str(len(bomb)).encode() + b"\r\n\r\n" + bomb
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(_serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    tracemalloc.start()
    try:
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.DecodingError):
                await http_bounded.fetch(
                    client, "GET", f"http://127.0.0.1:{port}/", max_bytes=200 << 20
                )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        server.close()
        for writer in writers:
            writer.close()
        await server.wait_closed()
    assert peak < 8 << 20
