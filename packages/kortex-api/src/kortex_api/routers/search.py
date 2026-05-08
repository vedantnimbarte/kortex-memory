"""Search router (hybrid only in M2; agentic /recall lands in M5)."""

from __future__ import annotations

from fastapi import APIRouter

from kortex_core.repositories.memory_repo import ScopeFilter
from kortex_core.services.retrieval_service import (
    RetrievalService,
    SearchRequest,
)

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.schemas.search import SearchHitOut, SearchIn, SearchOut

router = APIRouter(prefix="/v1/search", tags=["search"])


@router.post("", response_model=SearchOut)
async def search(
    payload: SearchIn, principal: PrincipalDep, session: SessionDep
) -> SearchOut:
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
