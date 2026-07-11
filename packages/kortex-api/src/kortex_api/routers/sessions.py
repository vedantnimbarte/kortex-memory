"""Sessions router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from kortex_core.services.session_service import SessionService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import not_found
from kortex_api.schemas.session import SessionIn, SessionOut

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    principal: PrincipalDep,
    session: SessionDep,
    project_public_id: uuid.UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SessionOut]:
    svc = SessionService(session, principal)
    sessions = await svc.list_for_project(project_public_id, limit=limit)
    return [SessionOut.model_validate(s) for s in sessions]


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def start_session(
    payload: SessionIn, principal: PrincipalDep, session: SessionDep
) -> SessionOut:
    svc = SessionService(session, principal)
    s = await svc.start(
        project_public_id=payload.project_public_id,
        agent_kind=payload.agent_kind,
        title=payload.title,
        client_metadata=payload.client_metadata,
    )
    if s is None:
        raise not_found("project not found")
    await session.commit()
    return SessionOut.model_validate(s)


@router.get("/{public_id}", response_model=SessionOut)
async def get_session(
    public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> SessionOut:
    svc = SessionService(session, principal)
    s = await svc.get(public_id)
    if s is None:
        raise not_found("session not found")
    return SessionOut.model_validate(s)


@router.post("/{public_id}/end", response_model=SessionOut)
async def end_session(
    public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> SessionOut:
    svc = SessionService(session, principal)
    s = await svc.end(public_id)
    if s is None:
        raise not_found("session not found")
    await session.commit()
    return SessionOut.model_validate(s)
