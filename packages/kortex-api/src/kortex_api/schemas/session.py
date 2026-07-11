"""Session/Conversation/Message schemas."""

from __future__ import annotations

import datetime as dt
import uuid

from kortex_core.db.types import AgentKind, MessageRole
from pydantic import Field

from kortex_api.schemas.common import APIModel, TimestampedOut


class SessionIn(APIModel):
    project_public_id: uuid.UUID
    agent_kind: AgentKind = AgentKind.OTHER
    title: str = ""
    client_metadata: dict = Field(default_factory=dict)


class SessionOut(TimestampedOut):
    agent_kind: AgentKind
    title: str
    client_metadata: dict
    started_at: dt.datetime
    ended_at: dt.datetime | None


class ConversationIn(APIModel):
    title: str = ""


class ConversationOut(TimestampedOut):
    title: str
    summary: str | None


class MessageIn(APIModel):
    role: MessageRole
    content: str = Field(max_length=100_000)
    tool_name: str | None = None
    tool_input: dict | None = None
    tool_output: dict | None = None


class MessageOut(APIModel):
    public_id: uuid.UUID
    role: MessageRole
    content: str
    tool_name: str | None
    tool_input: dict | None
    tool_output: dict | None
    created_at: dt.datetime


class IngestMessagesIn(APIModel):
    messages: list[MessageIn] = Field(max_length=1_000)
