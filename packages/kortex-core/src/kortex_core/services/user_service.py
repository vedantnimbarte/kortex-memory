"""User service: invite, grant/revoke memberships."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import Role, ScopeType
from kortex_core.models.user import Membership, User
from kortex_core.repositories.membership_repo import MembershipRepository
from kortex_core.repositories.user_repo import UserRepository
from kortex_core.security.passwords import hash_password
from kortex_core.security.principal import Principal


class UserService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._users = UserRepository(session, principal=principal)
        self._memberships = MembershipRepository(session, principal=principal)

    async def create_with_password(
        self,
        *,
        email: str,
        password: str,
        display_name: str = "",
        is_superuser: bool = False,
    ) -> User:
        return await self._users.create(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
            is_superuser=is_superuser,
        )

    async def get_by_email(self, email: str) -> User | None:
        return await self._users.get_by_email(email)

    async def get(self, public_id: uuid.UUID) -> User | None:
        return await self._users.get_by_public_id(public_id)

    async def grant(
        self,
        *,
        user_id: int,
        scope_type: ScopeType,
        scope_id: int,
        role: Role,
    ) -> Membership:
        return await self._memberships.grant(
            user_id=user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            role=role,
        )

    async def revoke(
        self, *, user_id: int, scope_type: ScopeType, scope_id: int
    ) -> bool:
        return await self._memberships.revoke(
            user_id=user_id, scope_type=scope_type, scope_id=scope_id
        )
