"""API key + JWT revocation models."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    ARRAY,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kortex_core.db.base import Base
from kortex_core.models.mixins import PublicIdMixin, TimestampMixin
from kortex_core.models.user import scope_type_enum

if TYPE_CHECKING:
    from kortex_core.models.org import Org


class ApiKey(Base, PublicIdMixin, TimestampMixin):
    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_prefix", "prefix"),
        Index("ix_api_keys_org_active", "org_id", "revoked_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    scope_type: Mapped[str | None] = mapped_column(scope_type_enum, nullable=True)
    scope_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    org: Mapped[Org] = relationship(back_populates="api_keys")


class JwtRevocation(Base):
    __tablename__ = "jwt_revocations"

    jti: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
