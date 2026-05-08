"""Workspace service."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.models.org import Workspace
from kortex_core.repositories.workspace_repo import WorkspaceRepository
from kortex_core.security.principal import Principal


class WorkspaceService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._repo = WorkspaceRepository(session, principal=principal)

    async def create(self, *, slug: str, name: str) -> Workspace:
        return await self._repo.create(slug=slug, name=name)

    async def list_(self) -> list[Workspace]:
        return await self._repo.list_for_org()

    async def get(self, public_id: uuid.UUID) -> Workspace | None:
        return await self._repo.get_by_public_id(public_id)

    async def get_by_slug(self, slug: str) -> Workspace | None:
        return await self._repo.get_by_slug(slug)
