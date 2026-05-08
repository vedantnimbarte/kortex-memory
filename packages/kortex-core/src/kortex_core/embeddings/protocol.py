"""Embedder protocol."""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol, runtime_checkable


class EmbeddingError(Exception):
    """Raised when an embedding call fails."""


@runtime_checkable
class Embedder(Protocol):
    """An embedder takes text and returns dense vectors.

    Implementations should be safe to instantiate once and call concurrently.
    """

    model_id: str
    """Stable identifier persisted alongside vectors so we can reindex."""

    dim: int
    """Output dimension."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per input, in order."""
        ...
