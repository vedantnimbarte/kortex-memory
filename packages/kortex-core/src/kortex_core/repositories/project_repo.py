"""Project repository."""

from __future__ import annotations

import uuid

from kortex_core.models.org import Project
from kortex_core.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    model = Project

    async def list_for_workspace(self, workspace_id: int) -> list[Project]:
        stmt = (
            self.tenant_query()
            .where(
                Project.workspace_id == workspace_id, Project.deleted_at.is_(None)
            )
            .order_by(Project.id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_by_public_id(self, public_id: uuid.UUID) -> Project | None:
        stmt = self.tenant_query().where(
            Project.public_id == public_id, Project.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, project_id: int) -> Project | None:
        stmt = self.tenant_query().where(
            Project.id == project_id, Project.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_slug(self, workspace_id: int, slug: str) -> Project | None:
        stmt = self.tenant_query().where(
            Project.workspace_id == workspace_id,
            Project.slug == slug,
            Project.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, *, workspace_id: int, slug: str, name: str) -> Project:
        project = Project(
            org_id=self.principal.org_id,
            workspace_id=workspace_id,
            slug=slug,
            name=name,
            settings={},
        )
        self._session.add(project)
        await self._session.flush()
        return project
