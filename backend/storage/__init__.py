"""Object-storage provider + FastAPI dependency.

``get_storage`` is the single seam routes depend on. In production it lazily
builds one :class:`MinioStorage` (which connects + ensures the bucket on first
use); tests override this dependency with an in-memory double so no MinIO is
needed (ADR-0006).
"""

from __future__ import annotations

from functools import lru_cache

from storage.base import ObjectStorage


@lru_cache(maxsize=1)
def _minio_storage() -> ObjectStorage:
    # Imported lazily so importing this package (and thus the app) never
    # requires the MinIO client to connect — only the first real request does.
    from storage.minio_storage import MinioStorage

    return MinioStorage()


def get_storage() -> ObjectStorage:
    return _minio_storage()
