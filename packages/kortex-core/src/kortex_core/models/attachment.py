"""Attachment + AttachmentChunk.

An attachment is the original blob the user uploaded (PDF/docx/markdown/etc.).
After ``process_attachment`` runs, text is extracted, chunked, embedded, and
written to ``attachment_chunks`` for retrieval. Chunks share the same hybrid
search substrate as memories (HNSW + GIN tsvector + trigram).
"""

from __future__ import annotations

import datetime as dt

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, REGCONFIG, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kortex_core.db.base import Base
from kortex_core.db.types import AttachmentStatus, Sensitivity
from kortex_core.embeddings.dimensions import EMBEDDING_DIM
from kortex_core.models.mixins import PublicIdMixin, SoftDeleteMixin, TimestampMixin
from kortex_core.models.user import scope_type_enum

attachment_status_enum = ENUM(
    *[s.value for s in AttachmentStatus],
    name="attachment_status",
    create_type=False,
)
sensitivity_enum = ENUM(
    *[s.value for s in Sensitivity],
    name="sensitivity",
    create_type=False,
)


class Attachment(Base, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    """An uploaded file, scoped to org/workspace/project/session."""

    __tablename__ = "attachments"
    __table_args__ = (
        Index(
            "ix_attachments_tenant",
            "org_id",
            "scope_type",
            "scope_id",
            "deleted_at",
        ),
        Index("ix_attachments_status", "processing_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(scope_type_enum, nullable=False)
    scope_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    filename: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    mime: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    s3_bucket: Mapped[str] = mapped_column(String(200), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)

    sensitivity: Mapped[str] = mapped_column(
        sensitivity_enum, nullable=False, default=Sensitivity.INTERNAL.value
    )
    processing_status: Mapped[str] = mapped_column(
        attachment_status_enum,
        nullable=False,
        default=AttachmentStatus.PENDING.value,
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    chunks: Mapped[list[AttachmentChunk]] = relationship(
        back_populates="attachment",
        cascade="all, delete-orphan",
        order_by="AttachmentChunk.chunk_index",
    )


class AttachmentChunk(Base, TimestampMixin):
    """One text chunk of an attachment, with its own embedding + tsvector."""

    __tablename__ = "attachment_chunks"
    __table_args__ = (
        Index(
            "ix_attachment_chunks_attachment_idx",
            "attachment_id",
            "chunk_index",
            unique=True,
        ),
        Index("ix_attachment_chunks_tenant", "org_id", "attachment_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    attachment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("attachments.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    ts_config: Mapped[str] = mapped_column(
        REGCONFIG,
        nullable=False,
        server_default=text("'english'::regconfig"),
    )
    """Analyser for this chunk, denormalised from the attachment's project."""

    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector(ts_config, coalesce(content,''))", persisted=True),
        nullable=False,
    )

    attachment: Mapped[Attachment] = relationship(back_populates="chunks")
