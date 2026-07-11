"""Reranker pipeline: turn fused hits into a rescored, budget-packed bundle."""

from __future__ import annotations

from dataclasses import dataclass

from kortex_core.retrieval.hybrid import HybridSearchHit
from kortex_core.retrieval.token_budget import BudgetItem, TokenBudget
from kortex_core.skills.reranker import RerankCandidate, Reranker


@dataclass(slots=True)
class RerankedHit:
    hit: HybridSearchHit
    rerank_score: float
    final_score: float


async def rerank_and_pack(
    *,
    query: str,
    hits: list[HybridSearchHit],
    reranker: Reranker,
    max_tokens: int,
    per_item_max: int = 800,
    blend: float = 0.7,
) -> tuple[list[RerankedHit], int]:
    """Score, blend, sort, then token-budget-pack.

    Final score is ``blend * normalized(rerank) + (1-blend) * normalized(prior)``.
    Pinned memories always rise to the top by their RRF floor (handled upstream).
    """
    if not hits:
        return [], 0

    candidates = [
        RerankCandidate(id=h.memory_id, text=f"{h.title}\n{h.body}", prior_score=h.score)
        for h in hits
    ]
    scores = await reranker.score(query, candidates)

    rerank_min = min(scores) if scores else 0.0
    rerank_span = (max(scores) - rerank_min) if scores else 1.0
    prior_min = min(h.score for h in hits)
    prior_span = max(1e-9, max(h.score for h in hits) - prior_min)

    reranked: list[RerankedHit] = []
    for hit, rscore in zip(hits, scores, strict=True):
        norm_r = (rscore - rerank_min) / (rerank_span or 1.0)
        norm_p = (hit.score - prior_min) / prior_span
        final = blend * norm_r + (1 - blend) * norm_p
        reranked.append(RerankedHit(hit=hit, rerank_score=rscore, final_score=final))

    reranked.sort(key=lambda r: r.final_score, reverse=True)

    budget = TokenBudget(max_tokens=max_tokens, per_item_max=per_item_max)
    kept_items, used = budget.fit(
        [
            BudgetItem(
                id=i,
                text=f"{r.hit.title}\n{r.hit.body}",
                score=r.final_score,
            )
            for i, r in enumerate(reranked)
        ]
    )
    kept_idx = {item.id for item in kept_items}
    final = [  # type: ignore[assignment]
        reranked[i] for i in sorted(kept_idx, key=lambda i: reranked[i].final_score, reverse=True)
    ]
    return final, used  # type: ignore[return-value]
