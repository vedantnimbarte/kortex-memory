"""Session, Conversation, Message repositories."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select

from kortex_core.db.types import AgentKind, MessageRole
from kortex_core.models.session import Conversation, Message, Session
from kortex_core.repositories.base import BaseRepository


class SessionRepository(BaseRepository[Session]):
    model = Session

    async def create(
        self,
        *,
        project_id: int,
        agent_kind: AgentKind = AgentKind.OTHER,
        title: str = "",
        client_metadata: dict | None = None,
    ) -> Session:
        session = Session(
            org_id=self.principal.org_id,
            project_id=project_id,
            agent_kind=agent_kind.value,
            title=title,
            client_metadata=dict(client_metadata) if client_metadata else {},
            started_at=dt.datetime.now(tz=dt.UTC),
        )
        self._session.add(session)
        await self._session.flush()
        return session

    async def get_by_public_id(self, public_id: uuid.UUID) -> Session | None:
        stmt = self.tenant_query().where(Session.public_id == public_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, session_id: int) -> Session | None:
        stmt = self.tenant_query().where(Session.id == session_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_project(self, project_id: int, *, limit: int = 50) -> list[Session]:
        stmt = (
            self.tenant_query()
            .where(Session.project_id == project_id)
            .order_by(Session.started_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def end(self, session: Session) -> Session:
        session.ended_at = dt.datetime.now(tz=dt.UTC)
        await self._session.flush()
        return session


class ConversationRepository(BaseRepository[Conversation]):
    model = Conversation

    async def create(
        self, *, session_id: int, title: str = ""
    ) -> Conversation:
        convo = Conversation(
            org_id=self.principal.org_id,
            session_id=session_id,
            title=title,
        )
        self._session.add(convo)
        await self._session.flush()
        return convo

    async def get_or_create_default(self, session_id: int) -> Conversation:
        stmt = (
            self.tenant_query()
            .where(Conversation.session_id == session_id)
            .order_by(Conversation.id)
            .limit(1)
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing
        return await self.create(session_id=session_id)

    async def get_by_public_id(self, public_id: uuid.UUID) -> Conversation | None:
        stmt = self.tenant_query().where(Conversation.public_id == public_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_session(self, session_id: int) -> list[Conversation]:
        stmt = (
            self.tenant_query()
            .where(Conversation.session_id == session_id)
            .order_by(Conversation.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())


class MessageRepository(BaseRepository[Message]):
    model = Message

    async def append(
        self,
        *,
        conversation_id: int,
        role: MessageRole,
        content: str,
        tool_name: str | None = None,
        tool_input: dict | None = None,
        tool_output: dict | None = None,
        created_at: dt.datetime | None = None,
    ) -> Message:
        message = Message(
            org_id=self.principal.org_id,
            conversation_id=conversation_id,
            role=role.value,
            content=content,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            created_at=created_at or dt.datetime.now(tz=dt.UTC),
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def list_for_conversation(
        self,
        conversation_id: int,
        *,
        limit: int = 200,
    ) -> list[Message]:
        stmt = (
            self.tenant_query()
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def append_bulk(
        self,
        *,
        conversation_id: int,
        items: list[dict],
    ) -> int:
        """Bulk-insert messages; returns count inserted."""
        if not items:
            return 0
        rows = []
        for item in items:
            rows.append(
                Message(
                    org_id=self.principal.org_id,
                    conversation_id=conversation_id,
                    role=MessageRole(item["role"]).value,
                    content=str(item.get("content", "")),
                    content_tokens=item.get("content_tokens"),
                    tool_name=item.get("tool_name"),
                    tool_input=item.get("tool_input"),
                    tool_output=item.get("tool_output"),
                    created_at=item.get("created_at") or dt.datetime.now(tz=dt.UTC),
                )
            )
        self._session.add_all(rows)
        await self._session.flush()
        return len(rows)
