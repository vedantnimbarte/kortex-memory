"""Plain hybrid retrieval (no LLM). Agentic retrieval lands in M5."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import Sensitivity
from kortex_core.embeddings.protocol import EmbeddingError
from kortex_core.embeddings.registry import get_embedder
from kortex_core.repositories.memory_repo import MemoryRepository, ScopeFilter
from kortex_core.retrieval.conflicts import annotate_conflicts, demote_superseded
from kortex_core.retrieval.hybrid import HybridSearchHit
from kortex_core.security.principal import Principal
from kortex_core.settings import get_settings


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    scopes: list[ScopeFilter] | None = None
    limit: int = 20
    embed_query: bool = True


@dataclass(frozen=True, slots=True)
class SearchResult:
    hits: list[HybridSearchHit]
    used_vector: bool


class RetrievalService:
    """Hybrid retrieval entrypoint.

    Embeds the query (when an embedder is available), runs vector + BM25 against
    the memories table, fuses via RRF, applies decay, and returns ranked hits.
    Sensitivity is bounded by the caller's effective sensitivity.
    """

    def __init__(self, session: AsyncSession, principal: Principal):
        self._session = session
        self._principal = principal
        self._memories = MemoryRepository(session, principal=principal)

    async def search(self, request: SearchRequest) -> SearchResult:
        query_vector: list[float] | None = None
        used_vector = False
        if request.embed_query:
            try:
                embedder = get_embedder()
                vectors = await embedder.embed([request.query])
                query_vector = vectors[0]
                used_vector = True
            except (EmbeddingError, KeyError, RuntimeError):
                # Fall back to BM25-only when embeddings aren't available.
                query_vector = None

        max_sensitivity = self._principal.max_sensitivity or Sensitivity.INTERNAL
        hits = await self._memories.hybrid_search(
            query=request.query,
            query_vector=query_vector,
            scopes=request.scopes,
            max_sensitivity=max_sensitivity,
            limit=request.limit,
        )
        # Surface stale/contradictory memories rather than quietly returning
        # the loser of a superseded pair.
        if get_settings().conflict_detection:
            demoted = await annotate_conflicts(self._session, self._principal, hits)
            hits = demote_superseded(hits, demoted, key=lambda h: h.memory_id)

        # Bookkeeping: bump access counters for what we returned.
        await self._memories.record_access([h.memory_id for h in hits])
        return SearchResult(hits=hits, used_vector=used_vector)
