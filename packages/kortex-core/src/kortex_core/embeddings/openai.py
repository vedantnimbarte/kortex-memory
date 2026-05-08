"""OpenAI embedder.

Uses ``text-embedding-3-large`` and truncates to 1024 dim via Matryoshka so
the storage layer stays uniform. The OpenAI SDK is async-native.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kortex_core.embeddings.protocol import Embedder, EmbeddingError
from kortex_core.settings import get_settings

if TYPE_CHECKING:
    from openai import AsyncOpenAI


class OpenAIEmbedder(Embedder):
    def __init__(
        self,
        model_id: str = "text-embedding-3-large",
        dim: int = 1024,
    ) -> None:
        self.model_id = model_id
        self.dim = dim
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> "AsyncOpenAI":
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as e:  # pragma: no cover
                raise EmbeddingError(
                    "openai not installed; install kortex-core[embeddings-openai]"
                ) from e
            s = get_settings()
            api_key = s.openai_api_key.get_secret_value() if s.openai_api_key else None
            if not api_key:
                raise EmbeddingError("OPENAI_API_KEY not configured")
            self._client = AsyncOpenAI(api_key=api_key)
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._get_client()
        resp = await client.embeddings.create(
            model=self.model_id,
            input=texts,
            dimensions=self.dim,
        )
        return [list(d.embedding) for d in resp.data]
