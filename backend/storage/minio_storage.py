"""MinIO/S3-backed :class:`ObjectStorage` (ARCHITECTURE.md §13.3).

Two clients on purpose: one bound to the internal endpoint the backend uses to
put/delete objects, and one bound to the *public* endpoint used only to sign
download URLs — so a browser-facing signed URL points at a host the browser can
actually reach (e.g. ``localhost:9000``) even when the backend talks to
``minio:9000`` inside the compose network. Both clients are pinned to a region so
signing is genuinely offline — without one the client makes a GetBucketLocation
call to the public endpoint at sign time, which the backend can't reach when that
endpoint is browser-facing only.

Credentials are the static key pair by default; ``MINIO_IAM_AUTH=true``
(ADR-0031, AWS deployments) swaps in the metadata-endpoint provider instead —
one shared instance for both clients, so role credentials are fetched and
refreshed once, not per client.
"""

from __future__ import annotations

import io
from datetime import timedelta

from minio import Minio
from minio.credentials import IamAwsProvider

from config import settings


class MinioStorage:
    def __init__(self) -> None:
        self._bucket = settings.minio_bucket
        if settings.minio_iam_auth:
            # ECS task role / EC2 instance profile (ADR-0031): resolved and
            # auto-refreshed from the AWS metadata endpoint; the static key
            # settings are ignored.
            auth: dict = {"credentials": IamAwsProvider()}
        else:
            auth = {
                "access_key": settings.minio_access_key,
                "secret_key": settings.minio_secret_key,
            }
        self._client = Minio(
            settings.minio_endpoint,
            secure=settings.minio_secure,
            region=settings.minio_region,
            **auth,
        )
        public_endpoint = settings.minio_public_endpoint or settings.minio_endpoint
        self._presign_client = Minio(
            public_endpoint,
            secure=settings.minio_secure,
            region=settings.minio_region,
            **auth,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            self._bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def get(self, key: str) -> bytes:
        response = self._client.get_object(self._bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def delete(self, key: str) -> None:
        self._client.remove_object(self._bucket, key)

    def presigned_get_url(
        self,
        key: str,
        expires_seconds: int,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        return self._presign_client.presigned_get_object(
            self._bucket,
            key,
            expires=timedelta(seconds=expires_seconds),
            response_headers=response_headers,
        )
