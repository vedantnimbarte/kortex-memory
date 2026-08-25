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
        raise KeyError(f"unknown embedder {name!r}; available: {', '.join(sorted(_factories))}")
    instance = _factories[name]()
    _singletons[name] = instance
    return instance


def reset() -> None:
    """Drop the singleton cache (tests only).

    Embedders are cached per name, so a test that changes KORTEX_EMBEDDER_DIM
    would otherwise keep getting an instance built under the old settings.
    """
    _singletons.clear()


def available_embedders() -> list[str]:
    """Registered embedder names, bootstrapping the defaults if needed."""
    _bootstrap_default_factories()
    return sorted(_factories)


def _bootstrap_default_factories() -> None:
    if "local_bge" not in _factories:
        from kortex_core.embeddings.local_bge import LocalBgeEmbedder

        _factories["local_bge"] = lambda: LocalBgeEmbedder()
    if "openai" not in _factories:
        from kortex_core.embeddings.openai import OpenAIEmbedder

        _factories["openai"] = lambda: OpenAIEmbedder()
    if "voyage" not in _factories:
        from kortex_core.embeddings.voyage import VoyageEmbedder

        _factories["voyage"] = lambda: VoyageEmbedder()
    if "ollama" not in _factories:
        from kortex_core.embeddings.ollama import OllamaEmbedder

        _factories["ollama"] = lambda: OllamaEmbedder()
    if "bedrock" not in _factories:
        from kortex_core.embeddings.bedrock import BedrockEmbedder

        _factories["bedrock"] = lambda: BedrockEmbedder()
