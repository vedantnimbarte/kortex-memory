"""Workspaces router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from kortex_core.services.workspace_service import WorkspaceService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import not_found
from kortex_api.schemas.org import WorkspaceIn, WorkspaceOut

router = APIRouter(prefix="/v1/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceIn, principal: PrincipalDep, session: SessionDep
) -> WorkspaceOut:
    svc = WorkspaceService(session, principal)
    ws = await svc.create(slug=payload.slug, name=payload.name)
    await session.commit()
    return WorkspaceOut.model_validate(ws)


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(principal: PrincipalDep, session: SessionDep) -> list[WorkspaceOut]:
    svc = WorkspaceService(session, principal)
    items = await svc.list_()
    return [WorkspaceOut.model_validate(w) for w in items]


@router.get("/{public_id}", response_model=WorkspaceOut)
async def get_workspace(
    public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> WorkspaceOut:
    svc = WorkspaceService(session, principal)
    ws = await svc.get(public_id)
    if ws is None:
        raise not_found("workspace not found")
    return WorkspaceOut.model_validate(ws)
