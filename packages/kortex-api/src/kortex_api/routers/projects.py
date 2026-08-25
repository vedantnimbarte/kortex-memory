"""Projects router (under workspaces)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from kortex_core.db.types import ScopeType
from kortex_core.services.project_service import ProjectService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import bad_request, not_found
from kortex_api.schemas.org import (
    ProjectIn,
    ProjectOut,
    ProjectReviewIn,
    ProjectTextSearchIn,
)

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


@router.patch("/{project_public_id}/text-search-config", response_model=ProjectOut)
async def set_text_search_config(
    project_public_id: uuid.UUID,
    payload: ProjectTextSearchIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> ProjectOut:
    """Choose how keyword search stems this project's text.

    Applies to memories already stored, not just future writes: changing the
    setting rewrites the analyser on every row in the project, which regenerates
    their search vectors. A setting that only took effect going forward would
    leave a French project with a corpus half-stemmed as English and no way to
    tell which half.
    """
    from kortex_core.repositories.attachment_repo import AttachmentChunkRepository
    from kortex_core.repositories.memory_repo import MemoryRepository
    from kortex_core.repositories.project_repo import ProjectRepository
    from kortex_core.retrieval.text_search import supported_configs

    if payload.text_search_config not in await supported_configs(session):
        raise bad_request(f"unknown text search configuration {payload.text_search_config!r}")

    repo = ProjectRepository(session, principal=principal)
    project = await repo.get_by_public_id(project_public_id)
    if project is None:
        raise not_found("project not found")
    project.text_search_config = payload.text_search_config
    for repo_cls in (MemoryRepository, AttachmentChunkRepository):
        await repo_cls(session, principal=principal).reanalyse_scope(
            scope_type=ScopeType.PROJECT,
            scope_id=project.id,
            ts_config=payload.text_search_config,
        )
    await session.flush()
    await session.commit()
    return ProjectOut.model_validate(project)
