"""Memory schemas."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from kortex_core.db.types import (
    MemoryKind,
    MemoryLinkType,
    MemorySource,
    MemoryTier,
    ScopeType,
    Sensitivity,
)
from pydantic import Field

from kortex_api.schemas.common import APIModel


class MemoryIn(APIModel):
    scope_type: ScopeType
    scope_id: int
    body: str = Field(min_length=1, max_length=100_000)
    title: str = Field(default="", max_length=1_000)
    kind: MemoryKind = MemoryKind.FACT
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    source_type: MemorySource = MemorySource.MANUAL
    source_ref: dict | None = None
    importance: float = Field(0.5, ge=0.0, le=1.0)
    pinned: bool = False
    metadata: dict = Field(default_factory=dict)
    expires_at: dt.datetime | None = None


class MemoryOut(APIModel):
    public_id: uuid.UUID
    scope_type: ScopeType
    scope_id: int
    title: str
    body: str
    kind: MemoryKind
    sensitivity: Sensitivity
    tier: MemoryTier
    importance: float
    pinned: bool
    access_count: int
    decay_score: float
    created_at: dt.datetime
    updated_at: dt.datetime
    last_accessed_at: dt.datetime | None
    expires_at: dt.datetime | None
    metadata_: dict = Field(alias="metadata")
    deduped: bool = False
    """True when this write folded into an existing identical memory rather
    than creating a new one. Only ever set on a create response."""
    embedding_state: Literal["ok", "pending", "failed"] = "pending"
    """``pending``/``failed`` mean this memory is not in vector search yet."""
    embed_attempts: int = 0
    embed_error: str | None = None


class CountSlice(APIModel):
    label: str
    value: int


class DecayHealth(APIModel):
    healthy: int
    aging: int
    faded: int


class AnalyticsOut(APIModel):
    count: int
    pinned: int
    avg_decay: float
    total_access: int
    by_tier: list[CountSlice]
    by_kind: list[CountSlice]
    by_sensitivity: list[CountSlice]
    decay_health: DecayHealth
    top_accessed: list[MemoryOut]
    timeline: list[int]


class MemoryUpdateIn(APIModel):
    title: str | None = Field(default=None, max_length=1_000)
    body: str | None = Field(default=None, min_length=1, max_length=100_000)
    kind: MemoryKind | None = None
    sensitivity: Sensitivity | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict | None = None


class MemoryBulkIn(APIModel):
    action: Literal["pin", "unpin", "delete"]
    public_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class MemoryBulkOut(APIModel):
    affected: int


class MemoryLinkIn(APIModel):
    to_public_id: uuid.UUID
    link_type: MemoryLinkType = MemoryLinkType.RELATED
    weight: float = 1.0


class MemoryLinkOut(APIModel):
    from_public_id: uuid.UUID
    to_public_id: uuid.UUID
    link_type: MemoryLinkType
    weight: float


class LinkedMemoryOut(APIModel):
    public_id: uuid.UUID
    title: str
    tier: MemoryTier
    link_type: MemoryLinkType
