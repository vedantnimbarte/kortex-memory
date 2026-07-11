"""Workspace service."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.models.org import Workspace
from kortex_core.repositories.org_repo import OrgRepository
from kortex_core.repositories.workspace_repo import WorkspaceRepository
from kortex_core.security.plan_limits import QuotaExceededError, max_workspaces
from kortex_core.security.principal import Principal


class WorkspaceService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._session = session
        self._principal = principal
        self._repo = WorkspaceRepository(session, principal=principal)

    async def create(self, *, slug: str, name: str) -> Workspace:
        await self._enforce_workspace_quota()
        return await self._repo.create(slug=slug, name=name)

    async def _enforce_workspace_quota(self) -> None:
        org = await OrgRepository(self._session, principal=self._principal).get_by_id(
            self._principal.org_id
        )
        cap = max_workspaces(org.plan if org else "free")
        if cap < 0:
            return  # unlimited
        if await self._repo.count_for_org(self._principal.org_id) >= cap:
            raise QuotaExceededError(
                f"workspace limit reached for the {org.plan if org else 'free'} plan "
                f"({cap}). Upgrade your plan to add workspaces."
            )

    async def list_(self) -> list[Workspace]:
        return await self._repo.list_for_org()

    async def get(self, public_id: uuid.UUID) -> Workspace | None:
        return await self._repo.get_by_public_id(public_id)

    async def get_by_slug(self, slug: str) -> Workspace | None:
        return await self._repo.get_by_slug(slug)
