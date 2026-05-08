"""Projects router (under workspaces)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from kortex_core.services.project_service import ProjectService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import not_found
from kortex_api.schemas.org import ProjectIn, ProjectOut

router = APIRouter(
    prefix="/v1/workspaces/{workspace_public_id}/projects", tags=["projects"]
)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    workspace_public_id: uuid.UUID,
    payload: ProjectIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> ProjectOut:
    svc = ProjectService(session, principal)
    project = await svc.create(
        workspace_public_id=workspace_public_id,
        slug=payload.slug,
        name=payload.name,
    )
    if project is None:
        raise not_found("workspace not found")
    await session.commit()
    return ProjectOut.model_validate(project)


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    workspace_public_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> list[ProjectOut]:
    svc = ProjectService(session, principal)
    projects = await svc.list_(workspace_public_id=workspace_public_id)
    return [ProjectOut.model_validate(p) for p in projects]


@router.get("/{project_public_id}", response_model=ProjectOut)
async def get_project(
    workspace_public_id: uuid.UUID,  # noqa: ARG001
    project_public_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
) -> ProjectOut:
    svc = ProjectService(session, principal)
    project = await svc.get(project_public_id)
    if project is None:
        raise not_found("project not found")
    return ProjectOut.model_validate(project)
