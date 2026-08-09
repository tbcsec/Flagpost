"""Bounded upload reading.

``UploadFile.read()`` with no argument pulls the whole (already-spooled) body
into one contiguous ``bytes`` before any size check can run — a handful of large
concurrent uploads can then spike RSS and OOM the worker. ``read_upload_capped``
reads in chunks and aborts with 413 the moment the running total crosses the
cap, so an oversized upload never fully materialises in memory. (Rejecting
*before* the body is spooled to disk is the job of an edge/ASGI body-size limit,
not this helper.)
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile, status

_CHUNK = 1 << 20  # 1 MiB


async def read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    """Read ``file`` into memory, raising 413 as soon as it exceeds ``max_bytes``
    so the peak allocation is bounded by the cap rather than the request size."""
    size = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds {max_bytes // (1024 * 1024)} MB limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)
