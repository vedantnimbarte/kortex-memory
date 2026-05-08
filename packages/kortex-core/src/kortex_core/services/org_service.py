"""Org service."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.models.org import Org
from kortex_core.repositories.org_repo import OrgRepository
from kortex_core.security.principal import Principal


class OrgService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._repo = OrgRepository(session, principal=principal)

    async def create(self, *, slug: str, name: str, plan: str = "free") -> Org:
        return await self._repo.create(slug=slug, name=name, plan=plan)

    async def list_(self) -> list[Org]:
        return await self._repo.list_for_principal()

    async def get(self, public_id: uuid.UUID) -> Org | None:
        return await self._repo.get_by_public_id(public_id)
