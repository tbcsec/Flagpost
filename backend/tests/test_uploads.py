"""Bounded upload reading (review #9): an oversized upload is rejected the moment
it crosses the cap, so it never fully materialises in memory."""

import io

import pytest
from fastapi import HTTPException, UploadFile

from utils.uploads import read_upload_capped


async def test_read_upload_capped_allows_within_limit():
    f = UploadFile(io.BytesIO(b"a" * 10), filename="x")
    assert await read_upload_capped(f, 10) == b"a" * 10


async def test_read_upload_capped_rejects_oversize_with_413():
    f = UploadFile(io.BytesIO(b"a" * 11), filename="x")
    with pytest.raises(HTTPException) as exc:
        await read_upload_capped(f, 10)
    assert exc.value.status_code == 413
