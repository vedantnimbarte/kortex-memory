"""Conversations + messages router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from kortex_core.services.session_service import ConversationService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import not_found
from kortex_api.schemas.session import (
    ConversationIn,
    ConversationOut,
    MessageIn,
    MessageOut,
)

router = APIRouter(tags=["conversations"])


@router.post(
    "/v1/sessions/{session_id}/conversations",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    session_id: uuid.UUID,
    payload: ConversationIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> ConversationOut:
    svc = ConversationService(session, principal)
    c = await svc.create_for_session(session_id, title=payload.title)
    if c is None:
        raise not_found("session not found")
    await session.commit()
    return ConversationOut.model_validate(c)


@router.get(
    "/v1/sessions/{session_id}/conversations",
    response_model=list[ConversationOut],
)
async def list_conversations(
    session_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[ConversationOut]:
    svc = ConversationService(session, principal)
    convos = await svc.list_for_session(session_id)
    return [ConversationOut.model_validate(c) for c in convos]


@router.post(
    "/v1/conversations/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def append_message(
    conversation_id: uuid.UUID,
    payload: MessageIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> MessageOut:
    svc = ConversationService(session, principal)
    msg = await svc.append_message(
        conversation_public_id=conversation_id,
        role=payload.role,
        content=payload.content,
        tool_name=payload.tool_name,
        tool_input=payload.tool_input,
        tool_output=payload.tool_output,
    )
    if msg is None:
        raise not_found("conversation not found")
    await session.commit()
    return MessageOut.model_validate(msg)


@router.get(
    "/v1/conversations/{conversation_id}/messages",
    response_model=list[MessageOut],
)
async def list_messages(
    conversation_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[MessageOut]:
    svc = ConversationService(session, principal)
    msgs = await svc.list_messages(conversation_id)
    return [MessageOut.model_validate(m) for m in msgs]
