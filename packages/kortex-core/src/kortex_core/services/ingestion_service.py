"""Ingestion service: bulk ingest of conversation messages and document text.

Memories are not extracted from messages here in M2 — that lands in M6 with
the LLM-driven extractor. This module just persists raw messages and surfaces
a hook to derive memories later.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import (
    MemoryKind,
    MemorySource,
    MessageRole,
    ScopeType,
    Sensitivity,
)
from kortex_core.models.memory import Memory
from kortex_core.repositories.session_repo import (
    ConversationRepository,
    MessageRepository,
)
from kortex_core.security.principal import Principal
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.session_service import SessionService


@dataclass(frozen=True, slots=True)
class IngestMessage:
    role: MessageRole
    content: str
    created_at: dt.datetime | None = None
    tool_name: str | None = None
    tool_input: dict | None = None
    tool_output: dict | None = None


@dataclass(frozen=True, slots=True)
class IngestSummary:
    session_public_id: uuid.UUID
    conversation_public_id: uuid.UUID
    messages_inserted: int
    memories_created: int


class IngestionService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._principal = principal
        self._sessions = SessionService(session, principal)
        self._convos = ConversationRepository(session, principal=principal)
        self._messages = MessageRepository(session, principal=principal)
        self._memories = MemoryService(session, principal)

    async def ingest_messages(
        self,
        *,
        session_public_id: uuid.UUID,
        items: Iterable[IngestMessage],
    ) -> IngestSummary | None:
        session = await self._sessions.get(session_public_id)
        if session is None:
            return None
        convo = await self._convos.get_or_create_default(session.id)
        rows: list[dict] = []
        for item in items:
            rows.append(
                {
                    "role": item.role.value,
                    "content": item.content,
                    "tool_name": item.tool_name,
                    "tool_input": item.tool_input,
                    "tool_output": item.tool_output,
                    "created_at": item.created_at,
                }
            )
        inserted = await self._messages.append_bulk(conversation_id=convo.id, items=rows)
        return IngestSummary(
            session_public_id=session.public_id,
            conversation_public_id=convo.public_id,
            messages_inserted=inserted,
            memories_created=0,
        )

    async def ingest_document(
        self,
        *,
        scope_type: ScopeType,
        scope_id: int,
        title: str,
        body: str,
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
        source_ref: dict | None = None,
    ) -> Memory:
        """Persist a whole document as a single memory. M4 will replace this
        with chunked attachment ingestion.
        """
        return await self._memories.create(
            CreateMemoryInput(
                scope_type=scope_type,
                scope_id=scope_id,
                title=title,
                body=body,
                kind=MemoryKind.PROCEDURE,
                sensitivity=sensitivity,
                source_type=MemorySource.DOCUMENT,
                source_ref=source_ref,
            )
        )

    async def ingest_git_log(
        self,
        *,
        scope_type: ScopeType,
        scope_id: int,
        commits: Iterable[dict],
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
    ) -> int:
        """Turn git commit summaries into memories.

        Each ``commit`` is expected to have ``sha`` and ``message`` keys, with
        optional ``author``, ``date``, ``files``. The commit message becomes
        the memory body; the sha is recorded in ``source_ref`` for traceback.
        """
        created = 0
        for commit in commits:
            sha = str(commit.get("sha") or "").strip()
            message = str(commit.get("message") or "").strip()
            if not sha or not message:
                continue
            title = message.splitlines()[0][:200]
            await self._memories.create(
                CreateMemoryInput(
                    scope_type=scope_type,
                    scope_id=scope_id,
                    title=title,
                    body=message,
                    kind=MemoryKind.EVENT,
                    sensitivity=sensitivity,
                    source_type=MemorySource.TOOL_OUTPUT,
                    source_ref={
                        "sha": sha,
                        "author": commit.get("author"),
                        "date": commit.get("date"),
                        "files": commit.get("files"),
                    },
                )
            )
            created += 1
        return created
