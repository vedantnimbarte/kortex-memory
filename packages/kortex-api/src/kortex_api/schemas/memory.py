"""Memory schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import Field

from kortex_core.db.types import (
    MemoryKind,
    MemoryLinkType,
    MemorySource,
    MemoryTier,
    ScopeType,
    Sensitivity,
)

from kortex_api.schemas.common import APIModel


class MemoryIn(APIModel):
    scope_type: ScopeType
    scope_id: int
    body: str = Field(min_length=1)
    title: str = ""
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


class MemoryUpdateIn(APIModel):
    title: str | None = None
    body: str | None = None
    kind: MemoryKind | None = None
    sensitivity: Sensitivity | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict | None = None


class MemoryLinkIn(APIModel):
    to_public_id: uuid.UUID
    link_type: MemoryLinkType = MemoryLinkType.RELATED
    weight: float = 1.0


class MemoryLinkOut(APIModel):
    from_public_id: uuid.UUID
    to_public_id: uuid.UUID
    link_type: MemoryLinkType
    weight: float
