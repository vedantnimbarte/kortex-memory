"""Amazon Bedrock embedder.

The single most-requested integration in the competitive research — and the
reason is rarely "we prefer Titan". It is that Bedrock keeps the data inside an
existing AWS account under an existing agreement, which is what makes a memory
layer approvable in an enterprise that will not send memories to a third-party
API.

Uses ``aiobotocore``, already a dependency of the S3 storage backend, so
Bedrock costs no new package. Titan v2 supports ``dimensions`` natively, so it
is asked for the schema width directly rather than truncated afterwards.

Bedrock's ``InvokeModel`` embeds one input per call, so a batch is N calls.
They are issued concurrently but bounded: an unbounded gather over a
64-item batch is how you turn a routine ingest into a throttling incident.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from kortex_core.embeddings.dimensions import check_dimension
from kortex_core.embeddings.protocol import Embedder, EmbeddingError
from kortex_core.settings import get_settings

DEFAULT_MODEL = "amazon.titan-embed-text-v2:0"
DEFAULT_DIM = 1024
MAX_CONCURRENCY = 8
"""Concurrent InvokeModel calls. Bedrock throttles per-account, and the
failure mode of over-parallelising is a ThrottlingException storm that fails
the whole batch rather than slowing it down."""


def build_request(model_id: str, text: str, dim: int) -> str:
    """The JSON body for one embedding call.

    Titan and Cohere take different shapes, so the family is chosen by model
    id. Guessing wrong produces a ValidationException from AWS rather than a
    wrong vector, which is at least a loud failure.
    """
    if model_id.startswith("cohere."):
        return json.dumps({"texts": [text], "input_type": "search_document"})
    return json.dumps({"inputText": text, "dimensions": dim, "normalize": True})


def parse_response(model_id: str, payload: dict) -> list[float]:
    """Read one vector out of an InvokeModel response body."""
    if model_id.startswith("cohere."):
        rows = payload.get("embeddings")
        if not isinstance(rows, list) or not rows:
            raise EmbeddingError(f"bedrock/cohere: no `embeddings` in response {sorted(payload)}")
        return [float(x) for x in rows[0]]
    vector = payload.get("embedding")
    if not isinstance(vector, list):
        raise EmbeddingError(f"bedrock/titan: no `embedding` in response {sorted(payload)}")
    return [float(x) for x in vector]


class BedrockEmbedder(Embedder):
    def __init__(self, model_id: str | None = None, dim: int | None = None) -> None:
        s = get_settings()
        self.model_id = model_id or (
            s.embedder_model if s.embedder == "bedrock" and s.embedder_model else DEFAULT_MODEL
        )
        self.dim = dim or (s.embedder_dim if s.embedder == "bedrock" else DEFAULT_DIM)
        check_dimension(name="bedrock", model_id=self.model_id, dim=self.dim)
        self._region = s.aws_region
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    def _session_factory(self) -> Any:
        try:
            from aiobotocore.session import get_session
        except ImportError as e:  # pragma: no cover - optional extra
            raise EmbeddingError(
                "aiobotocore not installed; install kortex-core[storage-s3] "
                "(Bedrock reuses the same AWS client stack)"
            ) from e
        return get_session()

    async def _embed_one(self, client: Any, text: str) -> list[float]:
        async with self._semaphore:
            resp = await client.invoke_model(
                modelId=self.model_id,
                body=build_request(self.model_id, text, self.dim),
                accept="application/json",
                contentType="application/json",
            )
            raw = await resp["body"].read()
        return parse_response(self.model_id, json.loads(raw))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        session = self._session_factory()
        try:
            async with session.create_client("bedrock-runtime", region_name=self._region) as client:
                # gather preserves input order, which is what binds each vector
                # back to the memory it belongs to.
                return await asyncio.gather(*(self._embed_one(client, t) for t in texts))
        except EmbeddingError:
            raise
        except Exception as e:  # botocore raises a wide family of client errors
            raise EmbeddingError(f"bedrock embedding call failed ({self._region}): {e}") from e
