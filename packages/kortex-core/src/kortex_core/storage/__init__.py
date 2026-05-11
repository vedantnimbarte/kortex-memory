"""Pluggable blob storage. Default is S3-compatible (MinIO/S3/R2)."""

from kortex_core.storage.protocol import (
    BlobMetadata,
    BlobStore,
    PresignedUpload,
    StorageError,
)
from kortex_core.storage.registry import get_blob_store, register_blob_store

__all__ = [
    "BlobMetadata",
    "BlobStore",
    "PresignedUpload",
    "StorageError",
    "get_blob_store",
    "register_blob_store",
]
