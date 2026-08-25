"""Search schemas."""

from __future__ import annotations

from kortex_core.db.types import ScopeType
from pydantic import Field

from kortex_api.schemas.common import APIModel


class ScopeFilterIn(APIModel):
    scope_type: ScopeType
    scope_id: int


class SearchIn(APIModel):
    query: str = Field(min_length=1, max_length=2000)
    scopes: list[ScopeFilterIn] | None = None
    limit: int = Field(20, ge=1, le=200)
    embed_query: bool = True


class ConflictNoteOut(APIModel):
    """A memory that conflicts with the one carrying this note.

    ``relation`` is stated from the annotated memory's point of view:
    ``superseded_by`` means *this* memory is the stale side.
    """

    public_id: str
    title: str
    relation: str
    created_at: str


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
    conflicts: list[ConflictNoteOut] = Field(default_factory=list)


class SearchOut(APIModel):
    hits: list[SearchHitOut]
    used_vector: bool


class RecallIn(APIModel):
    query: str = Field(min_length=1, max_length=2000)
    scopes: list[ScopeFilterIn] | None = None
    synthesize: bool = False
    max_tokens: int = Field(default=0, ge=0, le=32_000)
    per_item_max: int = Field(default=800, ge=64, le=4000)
    latency_budget_ms: int = Field(default=0, ge=0, le=600_000)
    """Wall-clock ceiling for the whole call; 0 means unlimited. A budget too
    small for a planner round trip degrades to plain hybrid retrieval rather
    than overshooting."""
    token_budget: int = Field(default=0, ge=0, le=1_000_000)
    """Ceiling on LLM tokens spent planning and synthesising; 0 = unlimited."""


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
    conflicts: list[ConflictNoteOut] = Field(default_factory=list)


class UsageOut(APIModel):
    """What the recall actually cost.

    ``cost_usd`` is null when the model has no configured price
    (``KORTEX_LLM_PRICES``) — null means unpriced, not free.
    """

    mode: str
    tokens_in: int
    tokens_out: int
    total_tokens: int
    llm_calls: int
    plan_steps: int
    hops: int
    latency_ms: float
    cost_usd: float | None = None
    budget_exhausted: bool = False


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
    usage: UsageOut
