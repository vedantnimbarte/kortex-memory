"""HeuristicReranker + rerank_and_pack."""

from __future__ import annotations

from kortex_core.retrieval.hybrid import HybridSearchHit
from kortex_core.retrieval.reranker_pipeline import rerank_and_pack
from kortex_core.skills.reranker import HeuristicReranker, RerankCandidate


async def test_heuristic_reranker_scores_token_overlap() -> None:
    reranker = HeuristicReranker()
    scores = await reranker.score(
        "redis caching",
        [
            RerankCandidate(id=1, text="we use Redis for caching", prior_score=0.5),
            RerankCandidate(id=2, text="deployment pipeline", prior_score=0.5),
        ],
    )
    assert scores[0] > scores[1]


async def test_rerank_and_pack_orders_by_blended_score() -> None:
    hits = [
        HybridSearchHit(
            memory_id=1,
            public_id="a",
            title="caching",
            body="redis ttl",
            tier="short",
            sensitivity="internal",
            importance=0.6,
            decay_score=1.0,
            pinned=False,
            score=0.5,
        ),
        HybridSearchHit(
            memory_id=2,
            public_id="b",
            title="deployment",
            body="github actions",
            tier="short",
            sensitivity="internal",
            importance=0.3,
            decay_score=1.0,
            pinned=False,
            score=0.5,
        ),
    ]
    kept, used = await rerank_and_pack(
        query="redis caching",
        hits=hits,
        reranker=HeuristicReranker(),
        max_tokens=200,
    )
    assert used > 0
    assert kept[0].hit.public_id == "a"
    assert kept[0].final_score >= kept[-1].final_score


async def test_rerank_and_pack_empty_hits() -> None:
    kept, used = await rerank_and_pack(
        query="x", hits=[], reranker=HeuristicReranker(), max_tokens=100
    )
    assert kept == [] and used == 0
