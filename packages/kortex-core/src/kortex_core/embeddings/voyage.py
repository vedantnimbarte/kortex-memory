"""Voyage AI embedder.

Plain REST over httpx rather than the ``voyageai`` SDK: the request is one JSON
POST, and an SDK would be a dependency earning nothing.

``voyage-3`` is 1024-dimensional out of the box, which is exactly the schema
width, so no truncation is needed. Voyage also distinguishes query from
document embeddings via ``input_type``; we always embed documents here because
this adapter is only ever used for storage. Query-side asymmetry would need the
retrieval path to say which side it is on, and getting that wrong silently
degrades recall — better to not offer it than to offer it wrong.
"""

from __future__ import annotations

import httpx

from kortex_core.embeddings.dimensions import check_dimension
from kortex_core.embeddings.protocol import Embedder, EmbeddingError
from kortex_core.settings import get_settings

DEFAULT_MODEL = "voyage-3"
DEFAULT_DIM = 1024
API_URL = "https://api.voyageai.com/v1/embeddings"


def parse_response(payload: dict, expected: int) -> list[list[float]]:
    """Pull vectors out of a Voyage response, in the order they were sent.

    Voyage returns an ``index`` per row and does not promise ordering, so the
    rows are sorted by it. Getting this wrong would attach every embedding to
    the wrong memory — a corruption that looks like bad retrieval rather than
    like a bug.
    """
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise EmbeddingError(f"voyage: response has no `data` array (keys: {sorted(payload)})")
    try:
        ordered = sorted(rows, key=lambda r: int(r["index"]))
    except (KeyError, TypeError, ValueError) as e:
        raise EmbeddingError(f"voyage: response rows missing a usable `index` ({e})") from e
    vectors = [[float(x) for x in row["embedding"]] for row in ordered]
    if len(vectors) != expected:
        raise EmbeddingError(f"voyage: asked for {expected} embeddings, got {len(vectors)}")
    return vectors


class VoyageEmbedder(Embedder):
    def __init__(self, model_id: str | None = None, dim: int | None = None) -> None:
        s = get_settings()
        self.model_id = model_id or (
            s.embedder_model if s.embedder == "voyage" and s.embedder_model else DEFAULT_MODEL
        )
        self.dim = dim or (s.embedder_dim if s.embedder == "voyage" else DEFAULT_DIM)
        check_dimension(name="voyage", model_id=self.model_id, dim=self.dim)
        self._timeout = 60.0

    def _api_key(self) -> str:
        s = get_settings()
        key = s.voyage_api_key.get_secret_value() if s.voyage_api_key else None
        if not key:
            raise EmbeddingError("KORTEX_VOYAGE_API_KEY not configured")
        return key

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {
            "model": self.model_id,
            "input": texts,
            "input_type": "document",
            "output_dimension": self.dim,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    API_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key()}"},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as e:
            raise EmbeddingError(f"voyage embedding call failed: {e}") from e
        return parse_response(body, len(texts))
