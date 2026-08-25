"""Memory + MemoryLink (the heart of the system)."""

from __future__ import annotations

import datetime as dt

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kortex_core.db.base import Base
from kortex_core.db.types import (
    MemoryKind,
    MemoryLinkType,
    MemorySource,
    MemoryTier,
    Sensitivity,
)
from kortex_core.embeddings.dimensions import EMBEDDING_DIM
from kortex_core.models.mixins import PublicIdMixin, SoftDeleteMixin, TimestampMixin
from kortex_core.models.user import scope_type_enum

memory_tier_enum = ENUM(
    *[t.value for t in MemoryTier],
    name="memory_tier",
    create_type=False,
)
sensitivity_enum = ENUM(
    *[s.value for s in Sensitivity],
    name="sensitivity",
    create_type=False,
)
memory_kind_enum = ENUM(
    *[k.value for k in MemoryKind],
    name="memory_kind",
    create_type=False,
)
memory_source_enum = ENUM(
    *[s.value for s in MemorySource],
    name="memory_source",
    create_type=False,
)
memory_link_type_enum = ENUM(
    *[lt.value for lt in MemoryLinkType],
    name="memory_link_type",
    create_type=False,
)


class Memory(Base, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_tenant", "org_id", "scope_type", "scope_id", "deleted_at"),
        Index("ix_memories_tier_decay", "tier", "decay_score"),
        Index(
            "ix_memories_expires_at",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
        # The conflict scan runs every minute and is almost always empty; a
        # partial index keeps it from touching the table at all.
        # Dedup looks up by (tenant, scope, fingerprint) on every write, so it
        # has to be indexed or it is a seq scan per memory created.
        Index(
            "ix_memories_content_hash",
            "org_id",
            "scope_type",
            "scope_id",
            "content_hash",
            postgresql_where=text("content_hash IS NOT NULL AND deleted_at IS NULL"),
        ),
        # Operators need "how many are stuck" to be cheap; without this the
        # ingest-status query is a seq scan on the largest table.
        Index(
            "ix_memories_embed_failed",
            "embed_failed_at",
            postgresql_where=text("embed_failed_at IS NOT NULL"),
        ),
        Index(
            "ix_memories_conflict_pending",
            "id",
            postgresql_where=text(
                "conflict_checked_at IS NULL AND embedding IS NOT NULL AND deleted_at IS NULL"
            ),
        ),
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

    source_type: Mapped[str] = mapped_column(
        memory_source_enum, nullable=False, default=MemorySource.MANUAL.value
    )
    source_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    kind: Mapped[str] = mapped_column(
        memory_kind_enum, nullable=False, default=MemoryKind.FACT.value
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    body_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tier: Mapped[str] = mapped_column(
        memory_tier_enum, nullable=False, default=MemoryTier.SHORT.value
    )
    sensitivity: Mapped[str] = mapped_column(
        sensitivity_enum, nullable=False, default=Sensitivity.INTERNAL.value
    )
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_accessed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decay_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,''))",
            persisted=True,
        ),
        nullable=False,
    )

    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """SHA-256 of the normalised title+body, used to fold away verbatim
    rewrites. NULL on memories written before dedup existed, and on writes that
    asked to bypass it."""

    conflict_checked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """When the conflict judge last looked at this memory. NULL = still queued."""

    embed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embed_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Last embedding failure, kept so an operator can see *why* without log diving."""
    embed_failed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """Set once attempts are exhausted. Non-NULL means this memory is invisible to
    vector search and nothing will retry it until someone asks."""
    embed_next_attempt_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """Backoff gate. NULL = eligible now."""

    @property
    def embedding_state(self) -> str:
        """``ok`` | ``failed`` | ``pending`` — the honest answer to "is this
        memory actually searchable?"."""
        if self.embedding is not None:
            return "ok"
        return "failed" if self.embed_failed_at is not None else "pending"

    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryLink(Base):
    __tablename__ = "memory_links"
    __table_args__ = (Index("ix_memory_links_to", "to_memory_id"),)

    from_memory_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("memories.id", ondelete="CASCADE"),
        primary_key=True,
    )
    to_memory_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("memories.id", ondelete="CASCADE"),
        primary_key=True,
    )
    link_type: Mapped[str] = mapped_column(
        memory_link_type_enum,
        primary_key=True,
        default=MemoryLinkType.RELATED.value,
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    from_memory: Mapped[Memory] = relationship(foreign_keys=[from_memory_id])
    to_memory: Mapped[Memory] = relationship(foreign_keys=[to_memory_id])
