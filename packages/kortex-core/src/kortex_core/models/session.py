"""Session, Conversation, Message."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kortex_core.db.base import Base
from kortex_core.db.types import AgentKind, MessageRole
from kortex_core.models.mixins import PublicIdMixin, TimestampMixin

if TYPE_CHECKING:
    pass

agent_kind_enum = ENUM(
    *[ak.value for ak in AgentKind],
    name="agent_kind",
    create_type=False,
)
message_role_enum = ENUM(
    *[r.value for r in MessageRole],
    name="message_role",
    create_type=False,
)


class Session(Base, PublicIdMixin, TimestampMixin):
    """A logical agent run (one Claude Code session, etc.)."""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_org_project", "org_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    agent_kind: Mapped[str] = mapped_column(
        agent_kind_enum, nullable=False, default=AgentKind.OTHER.value
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    client_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Conversation(Base, PublicIdMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_session_id", "session_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), nullable=True
    )

    session: Mapped[Session] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base, PublicIdMixin):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(message_role_enum, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
