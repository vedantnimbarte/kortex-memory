"""Memory link repository."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import or_, select

from kortex_core.db.types import MemoryLinkType
from kortex_core.models.memory import MemoryLink
from kortex_core.repositories.base import BaseRepository


class MemoryLinkRepository(BaseRepository[MemoryLink]):
    model = MemoryLink

    async def link(
        self,
        *,
        from_memory_id: int,
        to_memory_id: int,
        link_type: MemoryLinkType = MemoryLinkType.RELATED,
        weight: float = 1.0,
    ) -> MemoryLink:
        link = MemoryLink(
            from_memory_id=from_memory_id,
            to_memory_id=to_memory_id,
            link_type=link_type.value,
            weight=weight,
            created_at=dt.datetime.now(tz=dt.UTC),
        )
        self._session.add(link)
        await self._session.flush()
        return link

    async def unlink(
        self,
        *,
        from_memory_id: int,
        to_memory_id: int,
        link_type: MemoryLinkType,
    ) -> bool:
        stmt = select(MemoryLink).where(  # tenancy: ok - ids tenant-resolved upstream
            MemoryLink.from_memory_id == from_memory_id,
            MemoryLink.to_memory_id == to_memory_id,
            MemoryLink.link_type == link_type.value,
        )
        link = (await self._session.execute(stmt)).scalar_one_or_none()
        if link is None:
            return False
        await self._session.delete(link)
        await self._session.flush()
        return True

    async def conflict_links(self, memory_ids: Sequence[int]) -> list[MemoryLink]:
        """Every supersedes/contradicts edge touching any of ``memory_ids``.

        One query for a whole result page — recall annotates every hit, so a
        per-hit lookup would turn one recall into N round trips.
        """
        if not memory_ids:
            return []
        ids = list(memory_ids)
        stmt = select(MemoryLink).where(  # tenancy: ok - ids tenant-resolved upstream
            MemoryLink.link_type.in_(
                [MemoryLinkType.SUPERSEDES.value, MemoryLinkType.CONTRADICTS.value]
            ),
            or_(
                MemoryLink.from_memory_id.in_(ids),
                MemoryLink.to_memory_id.in_(ids),
            ),
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def neighbors(
        self,
        memory_id: int,
        *,
        link_types: list[MemoryLinkType] | None = None,
    ) -> list[MemoryLink]:
        stmt = select(MemoryLink).where(  # tenancy: ok - ids tenant-resolved upstream
            or_(
                MemoryLink.from_memory_id == memory_id,
                MemoryLink.to_memory_id == memory_id,
            )
        )
        if link_types:
            stmt = stmt.where(MemoryLink.link_type.in_([lt.value for lt in link_types]))
        return list((await self._session.execute(stmt)).scalars().all())
