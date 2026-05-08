"""Session, Conversation, Message services."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import AgentKind, MessageRole
from kortex_core.models.session import Conversation, Message, Session
from kortex_core.repositories.project_repo import ProjectRepository
from kortex_core.repositories.session_repo import (
    ConversationRepository,
    MessageRepository,
    SessionRepository,
)
from kortex_core.security.principal import Principal


class SessionService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._session = session
        self._principal = principal
        self._repo = SessionRepository(session, principal=principal)
        self._projects = ProjectRepository(session, principal=principal)

    async def start(
        self,
        *,
        project_public_id: uuid.UUID,
        agent_kind: AgentKind = AgentKind.OTHER,
        title: str = "",
        client_metadata: dict | None = None,
    ) -> Session | None:
        project = await self._projects.get_by_public_id(project_public_id)
        if project is None:
            return None
        return await self._repo.create(
            project_id=project.id,
            agent_kind=agent_kind,
            title=title,
            client_metadata=client_metadata,
        )

    async def get(self, public_id: uuid.UUID) -> Session | None:
        return await self._repo.get_by_public_id(public_id)

    async def list_for_project(
        self, project_public_id: uuid.UUID, *, limit: int = 50
    ) -> list[Session]:
        project = await self._projects.get_by_public_id(project_public_id)
        if project is None:
            return []
        return await self._repo.list_for_project(project.id, limit=limit)

    async def end(self, public_id: uuid.UUID) -> Session | None:
        session = await self._repo.get_by_public_id(public_id)
        if session is None:
            return None
        return await self._repo.end(session)


class ConversationService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._principal = principal
        self._convos = ConversationRepository(session, principal=principal)
        self._sessions = SessionRepository(session, principal=principal)
        self._messages = MessageRepository(session, principal=principal)

    async def create_for_session(
        self, session_public_id: uuid.UUID, *, title: str = ""
    ) -> Conversation | None:
        session = await self._sessions.get_by_public_id(session_public_id)
        if session is None:
            return None
        return await self._convos.create(session_id=session.id, title=title)

    async def get(self, public_id: uuid.UUID) -> Conversation | None:
        return await self._convos.get_by_public_id(public_id)

    async def list_for_session(
        self, session_public_id: uuid.UUID
    ) -> list[Conversation]:
        session = await self._sessions.get_by_public_id(session_public_id)
        if session is None:
            return []
        return await self._convos.list_for_session(session.id)

    async def append_message(
        self,
        *,
        conversation_public_id: uuid.UUID,
        role: MessageRole,
        content: str,
        tool_name: str | None = None,
        tool_input: dict | None = None,
        tool_output: dict | None = None,
    ) -> Message | None:
        convo = await self._convos.get_by_public_id(conversation_public_id)
        if convo is None:
            return None
        return await self._messages.append(
            conversation_id=convo.id,
            role=role,
            content=content,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
        )

    async def list_messages(
        self, conversation_public_id: uuid.UUID, *, limit: int = 200
    ) -> list[Message]:
        convo = await self._convos.get_by_public_id(conversation_public_id)
        if convo is None:
            return []
        return await self._messages.list_for_conversation(convo.id, limit=limit)
