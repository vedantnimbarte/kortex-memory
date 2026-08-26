"""Append-only audit log.

Append-only is enforced, not merely intended: a trigger refuses UPDATE and
refuses DELETE outside a session that has opted in for retention, and every row
carries a hash chained to the previous one for its org. See migration kkx0011
for why both are there.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import ENUM, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kortex_core.db.base import Base
from kortex_core.db.types import ActorKind

actor_kind_enum = ENUM(
    *[ak.value for ak in ActorKind],
    name="actor_kind",
    create_type=False,
)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_org_created", "org_id", "created_at"),
        Index("ix_audit_log_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    actor_kind: Mapped[str] = mapped_column(actor_kind_enum, nullable=False)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """SHA-256 over this row's content and ``prev_hash``. Null on rows written
    before chaining existed; the verifier reports those as unchained rather
    than pretending they were covered."""
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """The previous entry's ``entry_hash`` for this org, or the genesis marker."""
