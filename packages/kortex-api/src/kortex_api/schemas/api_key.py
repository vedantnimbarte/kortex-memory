"""API key schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import Field

from kortex_core.db.types import ScopeType

from kortex_api.schemas.common import APIModel, TimestampedOut


class ApiKeyIn(APIModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(default_factory=list)
    scope_type: ScopeType | None = None
    scope_id: int | None = None
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyOut(TimestampedOut):
    prefix: str
    name: str
    scopes: list[str]
    scope_type: ScopeType | None
    scope_id: int | None
    expires_at: dt.datetime | None
    last_used_at: dt.datetime | None
    revoked_at: dt.datetime | None


class ApiKeyMintOut(ApiKeyOut):
    plaintext: str
    """Returned exactly once at creation. Store securely."""


class ApiKeyId(APIModel):
    public_id: uuid.UUID
