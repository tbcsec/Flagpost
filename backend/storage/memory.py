"""In-memory object storage — the test/dev double for ``ObjectStorage``.

Keeps the pytest suite infra-free (ADR-0006): no MinIO required. Signed URLs
are synthetic (``memory://…``) but carry an expiry so tests can assert one was
issued and honoured the requested TTL.
"""

from __future__ import annotations

import time


class InMemoryStorage:
    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._objects[key] = (data, content_type)

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    def presigned_get_url(self, key: str, expires_seconds: int) -> str:
        expires_at = int(time.time()) + expires_seconds
        return f"memory://challenge-files/{key}?expires={expires_at}"

    # Test-only helpers -----------------------------------------------------
    def exists(self, key: str) -> bool:
        return key in self._objects

    def read(self, key: str) -> bytes:
        return self._objects[key][0]
