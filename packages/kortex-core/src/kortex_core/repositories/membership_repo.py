"""Membership repository."""

from __future__ import annotations

from sqlalchemy import select

from kortex_core.db.types import Role, ScopeType
from kortex_core.models.user import Membership, User
from kortex_core.repositories.base import BaseRepository


class MembershipRepository(BaseRepository[Membership]):
    model = Membership

    async def list_for_user(self, user_id: int) -> list[Membership]:
        stmt = select(Membership).where(Membership.user_id == user_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_org_members(self, org_id: int) -> list[tuple[User, str]]:
        """Users with an org-scoped membership, paired with their role."""
        stmt = (
            select(User, Membership.role)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.scope_type == ScopeType.ORG.value,
                Membership.scope_id == org_id,
                User.deleted_at.is_(None),
            )
            .order_by(User.id)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(row[0], row[1]) for row in rows]

    async def get(self, *, user_id: int, scope_type: ScopeType, scope_id: int) -> Membership | None:
        stmt = select(Membership).where(
            Membership.user_id == user_id,
            Membership.scope_type == scope_type.value,
            Membership.scope_id == scope_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def grant(
        self,
        *,
        user_id: int,
        scope_type: ScopeType,
        scope_id: int,
        role: Role,
    ) -> Membership:
        existing = await self.get(user_id=user_id, scope_type=scope_type, scope_id=scope_id)
        if existing is not None:
            existing.role = role.value
            await self._session.flush()
            return existing
        membership = Membership(
            user_id=user_id,
            scope_type=scope_type.value,
            scope_id=scope_id,
            role=role.value,
        )
        self._session.add(membership)
        await self._session.flush()
        return membership

    async def revoke(self, *, user_id: int, scope_type: ScopeType, scope_id: int) -> bool:
        m = await self.get(user_id=user_id, scope_type=scope_type, scope_id=scope_id)
        if m is None:
            return False
        await self._session.delete(m)
        await self._session.flush()
        return True
