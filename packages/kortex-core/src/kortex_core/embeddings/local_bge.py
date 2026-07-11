"""Local BGE embedder via sentence-transformers.

Default model: ``BAAI/bge-large-en-v1.5`` (1024 dim). The model is loaded lazily
on first call and reused. Encoding is offloaded to a thread to avoid blocking
the event loop.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from kortex_core.embeddings.protocol import Embedder, EmbeddingError
from kortex_core.settings import get_settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class LocalBgeEmbedder(Embedder):
    """Local sentence-transformers embedder."""

    def __init__(self, model_id: str | None = None, dim: int | None = None) -> None:
        s = get_settings()
        self.model_id = model_id or s.embedder_model
        self.dim = dim or s.embedder_dim
        self._batch_size = s.embedder_batch_size
        self._model: SentenceTransformer | None = None
        self._load_lock = threading.Lock()

    def _load(self) -> SentenceTransformer:
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                    except ImportError as e:  # pragma: no cover
                        raise EmbeddingError(
                            "sentence-transformers not installed; "
                            "install kortex-core[embeddings-local]"
                        ) from e
                    self._model = SentenceTransformer(self.model_id)
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        loop = asyncio.get_running_loop()
        out = await loop.run_in_executor(
            None,
            lambda: model.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            ),
        )
        # The returned ndarray rows convert cleanly to lists of floats.
        return [list(map(float, row)) for row in out]
