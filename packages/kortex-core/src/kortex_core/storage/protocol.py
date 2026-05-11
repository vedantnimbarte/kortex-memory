"""``BlobStore`` protocol: store and retrieve binary content by ``(bucket, key)``.

Adapters live alongside (``s3.py`` for production, ``fs.py`` for dev/test).
Pick the adapter via :func:`kortex_core.storage.registry.get_blob_store`.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class StorageError(Exception):
    """Raised when a blob store operation fails."""


@dataclass(frozen=True, slots=True)
class BlobMetadata:
    """Metadata about a stored object."""

    bucket: str
    key: str
    size_bytes: int
    content_type: str | None = None
    etag: str | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    """Presigned URL the client uses to PUT an object directly to storage."""

    url: str
    method: str = "PUT"
    headers: dict[str, str] = field(default_factory=dict)
    expires_in: int = 900  # seconds


@runtime_checkable
class BlobStore(Protocol):
    """Adapter API. All methods are async-safe.

    Implementations must avoid leaking credentials in returned URLs unless the
    intent is presigning. They must be safe to call concurrently from many
    coroutines.
    """

    @abstractmethod
    async def presign_put(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str | None = None,
        size_hint: int | None = None,
        expires_in: int = 900,
    ) -> PresignedUpload:
        """Return a presigned URL for the client to PUT an object to."""

    @abstractmethod
    async def head(self, *, bucket: str, key: str) -> BlobMetadata | None:
        """Return metadata for an object, or ``None`` if it doesn't exist."""

    @abstractmethod
    async def get_bytes(self, *, bucket: str, key: str) -> bytes:
        """Read the full object body. For dev/small files only."""

    @abstractmethod
    async def put_bytes(
        self,
        *,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str | None = None,
    ) -> BlobMetadata:
        """Upload a small object inline (used by the FS adapter and tests)."""

    @abstractmethod
    async def delete(self, *, bucket: str, key: str) -> bool:
        """Delete an object. Returns True if it existed and was removed."""
