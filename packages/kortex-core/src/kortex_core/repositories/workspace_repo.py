"""Workspace repository."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from kortex_core.models.org import Workspace
from kortex_core.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace]):
    model = Workspace

    async def list_for_org(self) -> list[Workspace]:
        stmt = self.tenant_query().where(Workspace.deleted_at.is_(None)).order_by(Workspace.id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_by_slug(self, slug: str) -> Workspace | None:
        stmt = self.tenant_query().where(Workspace.slug == slug, Workspace.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_public_id(self, public_id: uuid.UUID) -> Workspace | None:
        stmt = self.tenant_query().where(
            Workspace.public_id == public_id, Workspace.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, *, slug: str, name: str) -> Workspace:
        ws = Workspace(org_id=self.principal.org_id, slug=slug, name=name, settings={})
        self._session.add(ws)
        await self._session.flush()
        return ws

    async def get_by_id(self, ws_id: int) -> Workspace | None:
        stmt = self.tenant_query().where(Workspace.id == ws_id, Workspace.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count_for_org(self, org_id: int) -> int:
        """Live workspace count for an org — drives plan quotas."""
        stmt = (
            select(func.count())
            .select_from(Workspace)
            .where(Workspace.org_id == org_id, Workspace.deleted_at.is_(None))
        )
        return int((await self._session.execute(stmt)).scalar_one())
