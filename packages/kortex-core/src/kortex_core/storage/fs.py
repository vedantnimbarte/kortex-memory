"""Filesystem-backed blob store for dev/test.

Stores objects under ``$KORTEX_FS_STORAGE_ROOT/<bucket>/<key>``. ``presign_put``
returns a ``file://`` URL that the test harness or a local handler can use to
write the body directly — production code should never construct one of these.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from kortex_core.settings import get_settings
from kortex_core.storage.protocol import (
    BlobMetadata,
    BlobStore,
    PresignedUpload,
    StorageError,
)


class FilesystemBlobStore(BlobStore):
    """Dev/test adapter that writes blobs under a local directory."""

    def __init__(self, root: str | None = None) -> None:
        self._root = Path(root or get_settings().fs_storage_root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, bucket: str, key: str) -> Path:
        # Treat slashes in `key` as directory separators.
        return self._root / bucket / key

    async def presign_put(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str | None = None,  # noqa: ARG002 - unused in fs
        size_hint: int | None = None,  # noqa: ARG002
        expires_in: int = 900,
    ) -> PresignedUpload:
        path = self._path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return PresignedUpload(
            url=path.as_uri(),
            method="PUT",
            headers={},
            expires_in=expires_in,
        )

    async def head(self, *, bucket: str, key: str) -> BlobMetadata | None:
        path = self._path(bucket, key)
        if not path.exists():
            return None
        body = path.read_bytes()
        return BlobMetadata(
            bucket=bucket,
            key=key,
            size_bytes=path.stat().st_size,
            sha256=hashlib.sha256(body).hexdigest(),
        )

    async def get_bytes(self, *, bucket: str, key: str) -> bytes:
        path = self._path(bucket, key)
        if not path.exists():
            raise StorageError(f"object not found: {bucket}/{key}")
        return path.read_bytes()

    async def put_bytes(
        self,
        *,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str | None = None,
    ) -> BlobMetadata:
        path = self._path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return BlobMetadata(
            bucket=bucket,
            key=key,
            size_bytes=len(body),
            content_type=content_type,
            sha256=hashlib.sha256(body).hexdigest(),
        )

    async def delete(self, *, bucket: str, key: str) -> bool:
        path = self._path(bucket, key)
        if not path.exists():
            return False
        path.unlink()
        return True
