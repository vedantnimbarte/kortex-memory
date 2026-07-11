"""S3-compatible blob store (aiobotocore).

Targets MinIO in dev and S3/R2 in prod. The client is constructed per-call from
a long-lived session so we never share botocore credentials across event loops.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from kortex_core.settings import get_settings
from kortex_core.storage.protocol import (
    BlobMetadata,
    BlobStore,
    PresignedUpload,
    StorageError,
)

if TYPE_CHECKING:
    from aiobotocore.client import AioBaseClient


def _import_aiobotocore() -> Any:
    try:
        from aiobotocore.session import get_session
    except ImportError as e:  # pragma: no cover - optional dep
        raise StorageError("aiobotocore not installed; install kortex-core[storage-s3]") from e
    return get_session()


class S3BlobStore(BlobStore):
    """S3-compatible adapter using ``aiobotocore``."""

    def __init__(self) -> None:
        s = get_settings()
        self._endpoint_url = s.s3_endpoint_url
        self._region = s.s3_region
        self._access_key = s.s3_access_key.get_secret_value()
        self._secret_key = s.s3_secret_key.get_secret_value()
        self._use_ssl = s.s3_use_ssl
        self._session = _import_aiobotocore()

    def _client(self) -> AioBaseClient:
        return self._session.create_client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            use_ssl=self._use_ssl,
        )

    async def presign_put(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str | None = None,
        size_hint: int | None = None,  # noqa: ARG002 - reserved for future use
        expires_in: int = 900,
    ) -> PresignedUpload:
        params: dict[str, Any] = {"Bucket": bucket, "Key": key}
        headers: dict[str, str] = {}
        if content_type:
            params["ContentType"] = content_type
            headers["Content-Type"] = content_type
        async with self._client() as client:
            url = await client.generate_presigned_url(
                ClientMethod="put_object",
                Params=params,
                ExpiresIn=expires_in,
                HttpMethod="PUT",
            )
        return PresignedUpload(url=url, method="PUT", headers=headers, expires_in=expires_in)

    async def head(self, *, bucket: str, key: str) -> BlobMetadata | None:
        async with self._client() as client:
            try:
                resp = await client.head_object(Bucket=bucket, Key=key)
            except client.exceptions.NoSuchKey:  # pragma: no cover - shape varies
                return None
            except Exception as e:
                msg = str(e)
                if "404" in msg or "Not Found" in msg or "NoSuchKey" in msg:
                    return None
                raise StorageError(f"head failed: {e}") from e
        return BlobMetadata(
            bucket=bucket,
            key=key,
            size_bytes=int(resp.get("ContentLength", 0)),
            content_type=resp.get("ContentType"),
            etag=(resp.get("ETag") or "").strip('"') or None,
        )

    async def get_bytes(self, *, bucket: str, key: str) -> bytes:
        async with self._client() as client:
            try:
                resp = await client.get_object(Bucket=bucket, Key=key)
            except Exception as e:
                raise StorageError(f"get failed: {e}") from e
            async with resp["Body"] as stream:
                return await stream.read()  # type: ignore[no-any-return]

    async def put_bytes(
        self,
        *,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str | None = None,
    ) -> BlobMetadata:
        async with self._client() as client:
            kw: dict[str, Any] = {"Bucket": bucket, "Key": key, "Body": body}
            if content_type:
                kw["ContentType"] = content_type
            try:
                resp = await client.put_object(**kw)
            except Exception as e:
                raise StorageError(f"put failed: {e}") from e
        return BlobMetadata(
            bucket=bucket,
            key=key,
            size_bytes=len(body),
            content_type=content_type,
            etag=(resp.get("ETag") or "").strip('"') or None,
            sha256=hashlib.sha256(body).hexdigest(),
        )

    async def delete(self, *, bucket: str, key: str) -> bool:
        async with self._client() as client:
            try:
                await client.delete_object(Bucket=bucket, Key=key)
                return True
            except Exception as e:
                msg = str(e)
                if "404" in msg or "NoSuchKey" in msg:
                    return False
                raise StorageError(f"delete failed: {e}") from e
