"""Object storage interface (ARCHITECTURE.md §13.3).

Challenge files live behind this abstraction so the rest of the app never
touches the MinIO client directly, and so the test suite can swap in an
in-memory implementation and stay infra-free (ADR-0006). Object keys are
namespaced ``<competition_id>/<challenge_id>/<name>`` by the caller — the
storage layer just stores what it's given.
"""

from __future__ import annotations

from typing import Protocol


class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store ``data`` at ``key``, overwriting any existing object."""
        ...

    def get(self, key: str) -> bytes:
        """Read the object at ``key`` back as bytes (used to clone files)."""
        ...

    def delete(self, key: str) -> None:
        """Remove the object at ``key`` (a no-op if it doesn't exist)."""
        ...

    def presigned_get_url(
        self,
        key: str,
        expires_seconds: int,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        """Return a short-lived, self-authorizing download URL for ``key``.

        Signing is a pure/offline operation — it must not require the object to
        exist or hit the network.

        ``response_headers`` overrides response headers the store serves the
        object with (e.g. ``response-content-disposition`` /
        ``response-content-type``), signed into the URL — used to force a neutral
        content-type + attachment disposition so a stored file can't render as
        active content inline.
        """
        ...
