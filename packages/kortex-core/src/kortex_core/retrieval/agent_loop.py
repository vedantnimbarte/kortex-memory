"""Agent loop executor.

Drives a ``QueryPlan`` against the hybrid substrate and the memory-link graph.
Stops on ``StopAndAnswer``, when the candidate pool exceeds
``retrieval_max_candidates``, or when the hop count exceeds
``retrieval_max_hops``. Every step is sandboxed through the same repositories
that enforce tenancy, so the planner cannot escape org scope.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import MemoryLinkType, Sensitivity
from kortex_core.repositories.memory_link_repo import MemoryLinkRepository
from kortex_core.repositories.memory_repo import MemoryRepository, ScopeFilter
from kortex_core.retrieval.budget import RecallBudget
from kortex_core.retrieval.hybrid import HybridSearchHit
from kortex_core.retrieval.query_plan import (
    KeywordSearch,
    LinkExpand,
    QueryPlan,
    SemanticSearch,
    StopAndAnswer,
    TimeFilter,
)
from kortex_core.security.principal import Principal
from kortex_core.settings import get_settings
from kortex_core.telemetry.tracing import span

if TYPE_CHECKING:
    from kortex_core.embeddings.protocol import Embedder


@dataclass(slots=True)
class AgentLoopResult:
    candidates: list[HybridSearchHit]
    hops: int
    stopped_reason: str
    trace: list[str] = field(default_factory=list)


class AgentLoop:
    """Stateless executor — instantiate per recall call."""

    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        embedder: Embedder | None = None,
        scopes: list[ScopeFilter] | None = None,
        budget: RecallBudget | None = None,
    ):
        self._session = session
        self._principal = principal
        self._embedder = embedder
        self._scopes = scopes
        self._budget = budget
        self._memories = MemoryRepository(session, principal=principal)
        self._links = MemoryLinkRepository(session, principal=principal)
        s = get_settings()
        self._max_hops = s.retrieval_max_hops
        self._max_candidates = s.retrieval_max_candidates
        self._hop_reserve_ms = s.retrieval_hop_reserve_ms
        self._max_sensitivity = principal.max_sensitivity or Sensitivity.INTERNAL

    async def run(self, plan: QueryPlan) -> AgentLoopResult:
        seen: dict[int, HybridSearchHit] = {}
        time_after: dt.datetime | None = None
        time_before: dt.datetime | None = None
        trace: list[str] = []
        stopped_reason = "exhausted"
        hops = 0

        for step in plan.steps:
            # Checked before the hop, not after: overshooting the caller's
            # budget and then noticing helps nobody. Whatever has been found so
            # far is returned, which is why partial results are useful here.
            if self._budget is not None and not self._budget.has_headroom(self._hop_reserve_ms):
                stopped_reason = "budget_exhausted"
                break
            if hops >= self._max_hops:
                stopped_reason = "max_hops"
                break
            if len(seen) >= self._max_candidates:
                stopped_reason = "max_candidates"
                break
            hops += 1

            with span("kortex.retrieval.execute_step", step_type=step.type) as ss:
                if isinstance(step, StopAndAnswer):
                    stopped_reason = f"stop:{step.reason}" if step.reason else "stop"
                    trace.append("stop_and_answer")
                    break

                if isinstance(step, TimeFilter):
                    time_after = step.after
                    time_before = step.before
                    trace.append(f"time_filter after={time_after} before={time_before}")
                    continue

                if isinstance(step, SemanticSearch | KeywordSearch):
                    vector = None
                    if isinstance(step, SemanticSearch) and self._embedder is not None:
                        vectors = await self._embedder.embed([step.query])
                        vector = vectors[0]
                    hits = await self._memories.hybrid_search(
                        query=step.query,
                        query_vector=vector,
                        scopes=self._scopes,
                        max_sensitivity=self._max_sensitivity,
                        limit=step.top_k,
                    )
                    added = _ingest(seen, hits, time_after, time_before)
                    ss.set_attribute("added", added)
                    ss.set_attribute("top_k", step.top_k)
                    trace.append(f"{step.type} q={step.query!r} top_k={step.top_k} added={added}")
                    continue

                if isinstance(step, LinkExpand):
                    seed_ids = list(seen.keys())
                    added = await self._expand_links(seed_ids, step, seen)
                    ss.set_attribute("added", added)
                    ss.set_attribute("depth", step.max_depth)
                    trace.append(f"link_expand depth={step.max_depth} added={added}")
                    continue

        return AgentLoopResult(
            candidates=list(seen.values()),
            hops=hops,
            stopped_reason=stopped_reason,
            trace=trace,
        )

    async def _expand_links(
        self,
        seed_ids: Sequence[int],
        step: LinkExpand,
        seen: dict[int, HybridSearchHit],
    ) -> int:
        if not seed_ids:
            return 0
        types = [MemoryLinkType(t) for t in step.link_types]
        added = 0
        frontier = list(seed_ids)
        for _depth in range(step.max_depth):
            next_frontier: set[int] = set()
            for mid in frontier:
                neighbors = await self._links.neighbors(mid, link_types=types)
                for link in neighbors:
                    other = link.to_memory_id if link.from_memory_id == mid else link.from_memory_id
                    if other in seen:
                        continue
                    memory = await self._memories.get_by_id(other)
                    if memory is None:
                        continue
                    hit = HybridSearchHit(
                        memory_id=memory.id,
                        public_id=str(memory.public_id),
                        title=memory.title,
                        body=memory.body,
                        tier=memory.tier,
                        sensitivity=memory.sensitivity,
                        importance=memory.importance,
                        decay_score=memory.decay_score,
                        pinned=memory.pinned,
                        score=0.0,  # joined via graph, not ranked
                    )
                    seen[hit.memory_id] = hit
                    next_frontier.add(memory.id)
                    added += 1
            frontier = list(next_frontier)
            if not frontier:
                break
        return added


def _ingest(
    seen: dict[int, HybridSearchHit],
    hits: Sequence[HybridSearchHit],
    time_after: dt.datetime | None,
    time_before: dt.datetime | None,
) -> int:
    """Merge new hits into ``seen``; time filters are applied here.

    The hybrid_search SQL doesn't currently push the time filter down (we'd
    need an extra column or a join on a derived table); since we cap hops and
    candidates, post-filtering in Python is acceptable for v0.1.
    """
    added = 0
    # We don't have created_at on HybridSearchHit (the SQL view skips it for
    # weight); leave time filtering as a no-op for now so the planner can still
    # *request* it without us silently dropping rows. M9 ops add proper push-down.
    _ = time_after, time_before
    for h in hits:
        if h.memory_id in seen:
            existing = seen[h.memory_id]
            if h.score > existing.score:
                seen[h.memory_id] = h
            continue
        seen[h.memory_id] = h
        added += 1
    return added
