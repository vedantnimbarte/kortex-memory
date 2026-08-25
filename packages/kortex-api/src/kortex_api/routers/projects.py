"""Projects router (under workspaces)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from kortex_core.services.project_service import ProjectService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import not_found
from kortex_api.schemas.org import ProjectIn, ProjectOut, ProjectReviewIn

router = APIRouter(prefix="/v1/workspaces/{workspace_public_id}/projects", tags=["projects"])


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


@router.patch("/{project_public_id}/review-mode", response_model=ProjectOut)
async def set_review_mode(
    project_public_id: uuid.UUID,
    payload: ProjectReviewIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> ProjectOut:
    """Choose whether writes to this project wait for a human.

    Per project rather than per org: a scratch project and one holding
    customer commitments do not want the same discipline, and forcing one
    setting on both means it gets turned off for everything.
    """
    from kortex_core.repositories.project_repo import ProjectRepository

    repo = ProjectRepository(session, principal=principal)
    project = await repo.get_by_public_id(project_public_id)
    if project is None:
        raise not_found("project not found")
    project.review_mode = payload.review_mode
    await session.flush()
    await session.commit()
    return ProjectOut.model_validate(project)
