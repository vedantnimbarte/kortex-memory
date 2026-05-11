"""Search schemas."""

from __future__ import annotations

from pydantic import Field

from kortex_core.db.types import ScopeType

from kortex_api.schemas.common import APIModel


class ScopeFilterIn(APIModel):
    scope_type: ScopeType
    scope_id: int


class SearchIn(APIModel):
    query: str = Field(min_length=1, max_length=2000)
    scopes: list[ScopeFilterIn] | None = None
    limit: int = Field(20, ge=1, le=200)
    embed_query: bool = True


class SearchHitOut(APIModel):
    public_id: str
    title: str
    body: str
    tier: str
    sensitivity: str
    importance: float
    decay_score: float
    pinned: bool
    score: float


class SearchOut(APIModel):
    hits: list[SearchHitOut]
    used_vector: bool


class RecallIn(APIModel):
    query: str = Field(min_length=1, max_length=2000)
    scopes: list[ScopeFilterIn] | None = None
    synthesize: bool = False
    max_tokens: int = Field(default=0, ge=0, le=32_000)
    per_item_max: int = Field(default=800, ge=64, le=4000)


class CitationOut(APIModel):
    public_id: str
    title: str
    score: float


class RecallCandidateOut(APIModel):
    public_id: str
    title: str
    body: str
    tier: str
    sensitivity: str
    final_score: float
    rerank_score: float


class ContextBundleOut(APIModel):
    query: str
    answer: str | None
    citations: list[CitationOut]
    candidates: list[RecallCandidateOut]
    used_tokens: int
    plan_trace: list[str]
    plan_rationale: str
    hops: int
    stopped_reason: str
