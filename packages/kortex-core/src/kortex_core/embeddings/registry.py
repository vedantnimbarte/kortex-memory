"""Embedder registry. Resolves the configured embedder by name."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from kortex_core.settings import get_settings

if TYPE_CHECKING:
    from kortex_core.embeddings.protocol import Embedder

_factories: dict[str, Callable[[], Embedder]] = {}
_singletons: dict[str, Embedder] = {}


def register_embedder(name: str, factory: Callable[[], Embedder]) -> None:
    _factories[name] = factory


def get_embedder(name: str | None = None) -> Embedder:
    name = name or get_settings().embedder
    if name in _singletons:
        return _singletons[name]
    if name not in _factories:
        # Lazy-import the default adapters here so importing the registry is cheap
        # and the heavy ML deps stay optional.
        _bootstrap_default_factories()
    if name not in _factories:
        raise KeyError(f"unknown embedder: {name}")
    instance = _factories[name]()
    _singletons[name] = instance
    return instance


def _bootstrap_default_factories() -> None:
    if "local_bge" not in _factories:
        from kortex_core.embeddings.local_bge import LocalBgeEmbedder

        _factories["local_bge"] = lambda: LocalBgeEmbedder()
    if "openai" not in _factories:
        from kortex_core.embeddings.openai import OpenAIEmbedder

        _factories["openai"] = lambda: OpenAIEmbedder()
