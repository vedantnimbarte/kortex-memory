"""Blob store registry. Wires ``KORTEX_STORAGE_BACKEND`` to a singleton adapter."""

from __future__ import annotations

from collections.abc import Callable

from kortex_core.settings import get_settings
from kortex_core.storage.protocol import BlobStore

_factories: dict[str, Callable[[], BlobStore]] = {}
_singletons: dict[str, BlobStore] = {}


def register_blob_store(name: str, factory: Callable[[], BlobStore]) -> None:
    _factories[name] = factory


def get_blob_store(name: str | None = None) -> BlobStore:
    """Return the configured singleton blob store.

    ``KORTEX_STORAGE_BACKEND`` selects the adapter (``s3``, ``fs``). Defaults to
    ``s3`` for parity with production; tests usually point it at ``fs``.
    """
    name = name or get_settings().storage_backend
    if name in _singletons:
        return _singletons[name]
    if name not in _factories:
        _bootstrap_default_factories()
    if name not in _factories:
        raise KeyError(f"unknown blob store backend: {name}")
    instance = _factories[name]()
    _singletons[name] = instance
    return instance


def _bootstrap_default_factories() -> None:
    if "s3" not in _factories:
        from kortex_core.storage.s3 import S3BlobStore

        _factories["s3"] = lambda: S3BlobStore()
    if "fs" not in _factories:
        from kortex_core.storage.fs import FilesystemBlobStore

        _factories["fs"] = lambda: FilesystemBlobStore()


def reset() -> None:
    """Drop the singleton cache (tests only)."""
    _singletons.clear()
