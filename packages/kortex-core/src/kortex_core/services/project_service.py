"""Project service."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.models.org import Project
from kortex_core.repositories.project_repo import ProjectRepository
from kortex_core.repositories.workspace_repo import WorkspaceRepository
from kortex_core.security.principal import Principal


class ProjectService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._projects = ProjectRepository(session, principal=principal)
        self._workspaces = WorkspaceRepository(session, principal=principal)

    async def create(
        self, *, workspace_public_id: uuid.UUID, slug: str, name: str
    ) -> Project | None:
        workspace = await self._workspaces.get_by_public_id(workspace_public_id)
        if workspace is None:
            return None
        return await self._projects.create(workspace_id=workspace.id, slug=slug, name=name)

    async def list_(self, *, workspace_public_id: uuid.UUID) -> list[Project]:
        workspace = await self._workspaces.get_by_public_id(workspace_public_id)
        if workspace is None:
            return []
        return await self._projects.list_for_workspace(workspace.id)

    async def get(self, public_id: uuid.UUID) -> Project | None:
        return await self._projects.get_by_public_id(public_id)
