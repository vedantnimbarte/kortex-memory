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
