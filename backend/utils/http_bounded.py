"""Bounded reading of outbound HTTP response bodies (GHSA-r7rp-46pp-x55q).

Counting bytes as they arrive is not enough with httpx alone: it decodes a
compressed body chunk by chunk with no limit on what one chunk expands to, so a
few hundred bytes of brotli — or gzip stacked on gzip — become gigabytes inside
a single decode call, before a caller's byte count ever sees them. :func:`fetch`
reads a body so that the cap holds:

- it refuses a ``Content-Length`` over the cap before reading anything;
- it asks for ``Accept-Encoding: identity``, so a conforming server doesn't
  compress at all;
- it reads the body raw and decodes at most **one** gzip or zlib-wrapped
  deflate layer itself, with ``max_length`` so no single step can produce more
  than the cap allows, and counts the raw bytes too, so input that decodes to
  nothing (a long gzip header, empty deflate blocks) can't stream on unbounded.
  One layer stays accepted because a static host (a mirror on object storage)
  can serve a stored ``Content-Encoding`` whatever the request asked for;
- it refuses br, zstd, stacked and unknown codings instead of decoding them.

A refused or malformed coding raises ``httpx.DecodingError`` — what httpx raises
for a body it can't decode — so callers keep the error handling they already
have. Going over the cap raises :class:`BodyTooLarge`. The overall deadline is
the caller's (an ``asyncio.timeout`` around the call), since only the caller
knows what its whole exchange may take.
"""

from __future__ import annotations

import zlib

import httpx

# Accepted as the one layer this module decodes. ``zlib.MAX_WBITS | 32`` takes a
# gzip or a zlib header, which covers "deflate" as RFC 9110 defines it.
_INFLATE_CODINGS = frozenset({"gzip", "x-gzip", "deflate"})


class BodyTooLarge(Exception):
    """The response declared, sent or decoded to more than the caller's cap."""


def _raw_limit(max_bytes: int, compressed: bool) -> int:
    """Wire bytes allowed for a body capped at ``max_bytes`` decoded. An
    uncompressed body is the cap exactly. A compressed one gets deflate's
    worst-case expansion (5 bytes per 64 KiB stored block, under 1/4096 of the
    size) plus 1 KiB for the gzip frame and a stored file name."""
    return max_bytes + max_bytes // 4096 + 1024 if compressed else max_bytes


def _inflater_for(response: httpx.Response):
    """A decompressor for the response's coding, ``None`` for an uncompressed
    body, or ``httpx.DecodingError`` for a coding this module won't decode."""
    header = response.headers.get("content-encoding", "")
    codings = [c.strip().lower() for c in header.split(",")]
    codings = [c for c in codings if c and c != "identity"]
    if not codings:
        return None
    if len(codings) == 1 and codings[0] in _INFLATE_CODINGS:
        return zlib.decompressobj(zlib.MAX_WBITS | 32)
    raise httpx.DecodingError(
        f"refusing Content-Encoding {header[:64]!r}: only one gzip/deflate layer is decoded"
    )


async def read_body(response: httpx.Response, max_bytes: int) -> bytes:
    """Read a streamed response's body, decoded, holding no more than
    ``max_bytes`` of it at any point. See the module docstring."""
    inflater = _inflater_for(response)
    raw_limit = _raw_limit(max_bytes, inflater is not None)
    try:
        declared = int(response.headers.get("content-length", ""))
    except ValueError:  # absent, or not a number: count instead
        declared = None
    if declared is not None and declared > raw_limit:
        raise BodyTooLarge
    if response.is_stream_consumed:
        # Only a response built in memory (a mock transport's) arrives already
        # read — httpx reads it at construction — so all that's left to bound
        # is its length. A response off the network always streams below.
        if len(response.content) > max_bytes:
            raise BodyTooLarge
        return response.content

    size = 0
    raw_size = 0
    chunks: list[bytes] = []
    async for data in response.aiter_raw():
        raw_size += len(data)
        if raw_size > raw_limit:
            raise BodyTooLarge
        while data:
            if inflater is None:
                out, data = data, b""
            else:
                if inflater.eof:
                    raise httpx.DecodingError("data after the end of the compressed body")
                try:
                    # At most one byte past the budget: zlib stops there and
                    # keeps the rest of the input as unconsumed_tail, so one
                    # call can never expand a chunk past the cap. (max_length 0
                    # would mean unlimited; the budget is always >= 0 here.)
                    out = inflater.decompress(data, max_bytes - size + 1)
                except zlib.error as exc:
                    raise httpx.DecodingError(f"malformed compressed body: {exc}") from exc
                data = inflater.unconsumed_tail
                if inflater.unused_data:
                    raise httpx.DecodingError("data after the end of the compressed body")
            size += len(out)
            if size > max_bytes:
                raise BodyTooLarge
            chunks.append(out)
    if inflater is not None and raw_size and not inflater.eof:
        raise httpx.DecodingError("truncated compressed body")
    return b"".join(chunks)


async def fetch(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_bytes: int,
    headers: dict[str, str] | None = None,
    **kwargs,
) -> tuple[httpx.Response, bytes]:
    """Send one request through ``client`` and return ``(response, body)``.

    The body is read, bounded as above, only for a 2xx status; any other status
    returns ``b""`` unread, so a caller's status check behaves as it did with a
    buffered response and an oversized error page can't mask the status. The
    response's status and headers stay readable after the stream closes.
    """
    request_headers = {**(headers or {}), "Accept-Encoding": "identity"}
    async with client.stream(method, url, headers=request_headers, **kwargs) as response:
        if not 200 <= response.status_code < 300:
            return response, b""
        return response, await read_body(response, max_bytes)
