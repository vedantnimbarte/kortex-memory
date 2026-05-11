"""Ingest router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from pydantic import Field

from kortex_core.db.types import ScopeType, Sensitivity
from kortex_core.services.ingestion_service import IngestionService, IngestMessage

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import not_found
from kortex_api.schemas.common import APIModel
from kortex_api.schemas.session import IngestMessagesIn

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])


class GitCommitIn(APIModel):
    sha: str = Field(min_length=4, max_length=64)
    message: str = Field(min_length=1)
    author: str | None = None
    date: str | None = None
    files: list[str] | None = None


class GitLogIngestIn(APIModel):
    scope_type: ScopeType
    scope_id: int
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    commits: list[GitCommitIn]


class GitLogIngestOut(APIModel):
    memories_created: int


@router.post(
    "/sessions/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED
)
async def ingest_messages(
    session_id: uuid.UUID,
    payload: IngestMessagesIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> dict:
    svc = IngestionService(session, principal)
    items = [
        IngestMessage(
            role=m.role,
            content=m.content,
            tool_name=m.tool_name,
            tool_input=m.tool_input,
            tool_output=m.tool_output,
        )
        for m in payload.messages
    ]
    summary = await svc.ingest_messages(
        session_public_id=session_id, items=items
    )
    if summary is None:
        raise not_found("session not found")
    await session.commit()
    return {
        "session_public_id": str(summary.session_public_id),
        "conversation_public_id": str(summary.conversation_public_id),
        "messages_inserted": summary.messages_inserted,
        "memories_created": summary.memories_created,
    }


@router.post(
    "/git-log",
    response_model=GitLogIngestOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_git_log(
    payload: GitLogIngestIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> GitLogIngestOut:
    svc = IngestionService(session, principal)
    created = await svc.ingest_git_log(
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        commits=[c.model_dump() for c in payload.commits],
        sensitivity=payload.sensitivity,
    )
    await session.commit()
    return GitLogIngestOut(memories_created=created)
