"""User and Membership."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT, ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kortex_core.db.base import Base
from kortex_core.db.types import Role, ScopeType
from kortex_core.models.mixins import PublicIdMixin, SoftDeleteMixin, TimestampMixin

role_enum = ENUM(
    *[r.value for r in Role],
    name="role",
    create_type=False,
)
scope_type_enum = ENUM(
    *[st.value for st in ScopeType],
    name="scope_type",
    create_type=False,
)


class User(Base, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "scope_type", "scope_id", name="uq_memberships_user_scope"
        ),
        Index("ix_memberships_scope", "scope_type", "scope_id"),
        Index("ix_memberships_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(scope_type_enum, nullable=False)
    scope_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(role_enum, nullable=False, default=Role.MEMBER.value)

    user: Mapped[User] = relationship(back_populates="memberships")
