"""``metadata`` on an ORM row is SQLAlchemy's, not the column's.

Every declarative class carries a class attribute called ``metadata`` holding
the ``MetaData`` registry, so the memory and attachment tables map their JSONB
column to ``metadata_`` instead. An out-schema that then asked pydantic to
*validate* by the alias ``metadata`` read the registry rather than the column
and raised on every single response — which took down the whole write path,
after the row had already been committed. These tests pin the read side to the
mapped attribute and the wire side to ``metadata``.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from kortex_api.schemas.attachment import AttachmentOut
from kortex_api.schemas.memory import MemoryOut
from kortex_core.db.types import MemoryKind, MemoryTier, ScopeType, Sensitivity
from kortex_core.models.memory import Memory
from sqlalchemy import MetaData


def _row() -> Memory:
    """An unsaved ORM row carrying both ``metadata`` and ``metadata_``."""
    now = dt.datetime.now(dt.UTC)
    row = Memory()
    row.public_id = uuid.uuid4()
    row.scope_type = ScopeType.PROJECT
    row.scope_id = 1
    row.title = "the queue runs on Redis"
    row.body = "Celery brokers through Redis, not RabbitMQ."
    row.kind = MemoryKind.FACT
    row.sensitivity = Sensitivity.INTERNAL
    row.tier = MemoryTier.SHORT
    row.importance = 0.5
    row.pinned = False
    row.access_count = 0
    row.decay_score = 1.0
    row.created_at = now
    row.updated_at = now
    row.last_accessed_at = None
    row.expires_at = None
    row.trust = "medium"
    row.pii_flags = {}
    row.review_status = "approved"
    row.embed_attempts = 0
    row.metadata_ = {"source": "seed"}
    return row


def test_memory_out_reads_the_mapped_column_not_the_sqlalchemy_registry() -> None:
    assert isinstance(Memory.metadata, MetaData)  # the trap this guards

    out = MemoryOut.model_validate(_row())

    assert out.metadata_ == {"source": "seed"}


def test_memory_out_still_serialises_the_column_as_metadata() -> None:
    """Clients read ``metadata``; the rename must not leak onto the wire."""
    dumped = MemoryOut.model_validate(_row()).model_dump(by_alias=True)

    assert dumped["metadata"] == {"source": "seed"}
    assert "metadata_" not in dumped


@pytest.mark.parametrize("schema", [MemoryOut, AttachmentOut])
def test_out_schemas_never_validate_metadata_by_alias(schema: type) -> None:
    """Both schemas map the same column and share the same failure mode."""
    field = schema.model_fields["metadata_"]

    assert field.validation_alias == "metadata_"
    assert field.serialization_alias == "metadata"
