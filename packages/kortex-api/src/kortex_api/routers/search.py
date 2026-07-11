"""Search router (hybrid + agentic recall)."""

from __future__ import annotations

from fastapi import APIRouter
from kortex_core.repositories.memory_repo import ScopeFilter
from kortex_core.security.quota import check_daily_quota
from kortex_core.services.agentic_retriever import (
    AgenticRetriever,
    RecallRequest,
)
from kortex_core.services.retrieval_service import (
    RetrievalService,
    SearchRequest,
)
from kortex_core.settings import get_settings

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import too_many_requests
from kortex_api.schemas.search import (
    CitationOut,
    ContextBundleOut,
    RecallCandidateOut,
    RecallIn,
    SearchHitOut,
    SearchIn,
    SearchOut,
)

router = APIRouter(prefix="/v1/search", tags=["search"])


@router.post("", response_model=SearchOut)
async def search(payload: SearchIn, principal: PrincipalDep, session: SessionDep) -> SearchOut:
    svc = RetrievalService(session, principal)
    scopes = (
        [ScopeFilter(scope_type=s.scope_type, scope_id=s.scope_id) for s in payload.scopes]
        if payload.scopes
        else None
    )
    result = await svc.search(
        SearchRequest(
            query=payload.query,
            scopes=scopes,
            limit=payload.limit,
            embed_query=payload.embed_query,
        )
    )
    await session.commit()
    return SearchOut(
        used_vector=result.used_vector,
        hits=[
            SearchHitOut(
                public_id=h.public_id,
                title=h.title,
                body=h.body,
                tier=h.tier,
                sensitivity=h.sensitivity,
                importance=h.importance,
                decay_score=h.decay_score,
                pinned=h.pinned,
                score=h.score,
            )
            for h in result.hits
        ],
    )


@router.post("/recall", response_model=ContextBundleOut)
async def recall(
    payload: RecallIn, principal: PrincipalDep, session: SessionDep
) -> ContextBundleOut:
    # Cost ceiling: recall drives planner + summarizer + embedding calls, so cap
    # cumulative daily use per org to bound the model bill (superusers exempt).
    cfg = get_settings()
    if not principal.is_superuser and not await check_daily_quota(
        bucket="recall", org_id=principal.org_id, limit=cfg.recall_daily_quota_per_org
    ):
        raise too_many_requests("daily recall quota exceeded for this organization")
    scopes = (
        [ScopeFilter(scope_type=s.scope_type, scope_id=s.scope_id) for s in payload.scopes]
        if payload.scopes
        else None
    )
    retriever = AgenticRetriever(session, principal)
    bundle = await retriever.recall(
        RecallRequest(
            query=payload.query,
            scopes=scopes,
            synthesize=payload.synthesize,
            max_tokens=payload.max_tokens,
            per_item_max=payload.per_item_max,
        )
    )
    await session.commit()
    return ContextBundleOut(
        query=bundle.query,
        answer=bundle.answer,
        citations=[
            CitationOut(public_id=c.public_id, title=c.title, score=c.score)
            for c in bundle.citations
        ],
        candidates=[
            RecallCandidateOut(
                public_id=r.hit.public_id,
                title=r.hit.title,
                body=r.hit.body,
                tier=r.hit.tier,
                sensitivity=r.hit.sensitivity,
                final_score=r.final_score,
                rerank_score=r.rerank_score,
            )
            for r in bundle.candidates
        ],
        used_tokens=bundle.used_tokens,
        plan_trace=bundle.plan_trace,
        plan_rationale=bundle.plan_rationale,
        hops=bundle.hops,
        stopped_reason=bundle.stopped_reason,
    )
