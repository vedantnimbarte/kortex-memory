"""Attachment schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from kortex_core.db.types import AttachmentStatus, ScopeType, Sensitivity
from pydantic import Field

from kortex_api.schemas.common import APIModel


class AttachmentPresignIn(APIModel):
    scope_type: ScopeType
    scope_id: int
    filename: str = Field(min_length=1, max_length=500)
    mime: str | None = None
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    size_hint: int | None = Field(default=None, ge=0)
    metadata: dict = Field(default_factory=dict)


class PresignedUploadOut(APIModel):
    url: str
    method: str
    headers: dict[str, str]
    expires_in: int


class AttachmentOut(APIModel):
    public_id: uuid.UUID
    scope_type: ScopeType
    scope_id: int
    filename: str
    mime: str | None
    size_bytes: int
    sha256: str | None
    sensitivity: Sensitivity
    processing_status: AttachmentStatus
    processing_error: str | None
    processed_at: dt.datetime | None
    s3_bucket: str
    s3_key: str
    created_at: dt.datetime
    updated_at: dt.datetime
    metadata_: dict = Field(alias="metadata")


class AttachmentPresignOut(APIModel):
    attachment: AttachmentOut
    upload: PresignedUploadOut


class AttachmentFinalizeIn(APIModel):
    sha256: str | None = None
    size_bytes: int | None = None
    mime: str | None = None


class AttachmentChunkHitOut(APIModel):
    attachment_public_id: str
    filename: str
    chunk_index: int
    content: str
    score: float


class AttachmentSearchOut(APIModel):
    hits: list[AttachmentChunkHitOut]
    used_vector: bool
