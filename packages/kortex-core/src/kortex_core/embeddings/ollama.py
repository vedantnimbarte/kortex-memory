"""Ollama embedder.

The reason to want this is air-gapped and self-hosted deployments: no API key,
no egress, no per-token cost. It mirrors the existing Ollama LLM adapter and
talks to the same ``ollama serve`` over plain HTTP, so it adds no dependency.

The dimension is the catch. Ollama serves whatever model you pulled, and most
embedding models are not 1024-dimensional — ``nomic-embed-text`` is 768,
``mxbai-embed-large`` is 1024. Ollama has no truncation parameter, so the model
either fits the schema or it does not, and the check at construction says which
rather than letting Postgres reject every write later.
"""

from __future__ import annotations

import httpx

from kortex_core.embeddings.dimensions import check_dimension
from kortex_core.embeddings.protocol import Embedder, EmbeddingError
from kortex_core.settings import get_settings

DEFAULT_MODEL = "mxbai-embed-large"
"""1024-dimensional, which is the schema width. `nomic-embed-text` is more
commonly pulled but is 768 and will not fit without a schema migration."""

DEFAULT_DIM = 1024


def parse_response(payload: dict, expected: int) -> list[list[float]]:
    """Read vectors from ``/api/embed``.

    Ollama has two shapes in the wild: ``embeddings`` (a list, from the newer
    batch endpoint) and ``embedding`` (a single vector, from the older one).
    Both are accepted because which you get depends on the daemon's version,
    not on anything the operator chose.
    """
    rows = payload.get("embeddings")
    if rows is None and "embedding" in payload:
        rows = [payload["embedding"]]
    if not isinstance(rows, list):
        raise EmbeddingError(
            f"ollama: response has neither `embeddings` nor `embedding` (keys: {sorted(payload)})"
        )
    vectors = [[float(x) for x in row] for row in rows]
    if len(vectors) != expected:
        raise EmbeddingError(f"ollama: asked for {expected} embeddings, got {len(vectors)}")
    return vectors


class OllamaEmbedder(Embedder):
    def __init__(self, model_id: str | None = None, dim: int | None = None) -> None:
        s = get_settings()
        self.model_id = model_id or (
            s.embedder_model if s.embedder == "ollama" and s.embedder_model else DEFAULT_MODEL
        )
        self.dim = dim or (s.embedder_dim if s.embedder == "ollama" else DEFAULT_DIM)
        check_dimension(name="ollama", model_id=self.model_id, dim=self.dim)
        self._base_url = s.ollama_base_url.rstrip("/")
        self._timeout = 120.0
        """Generous: a cold Ollama loads the model on the first request."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self.model_id, "input": texts},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as e:
            raise EmbeddingError(
                f"ollama embedding call failed ({self._base_url}): {e}. "
                f"Is `ollama serve` running and `{self.model_id}` pulled?"
            ) from e
        vectors = parse_response(body, len(texts))
        # Ollama silently serves whatever width the pulled model produces, so
        # the declared dimension is a claim until the first response proves it.
        if vectors and len(vectors[0]) != self.dim:
            raise EmbeddingError(
                f"ollama model {self.model_id!r} returned {len(vectors[0])}-dimensional "
                f"vectors, not the configured {self.dim}. Pull a {self.dim}-dim model "
                f"(e.g. mxbai-embed-large) or set KORTEX_EMBEDDER_DIM to match."
            )
        return vectors
