"""User repository.

Users are global to the SaaS — they live across orgs through memberships. The
"tenant" of a user is whichever org context the principal is operating in,
enforced via memberships rather than a column on ``users``.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select

from kortex_core.models.user import User
from kortex_core.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(
            User.email == email, User.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        stmt = select(User).where(
            User.id == user_id, User.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_public_id(self, public_id: uuid.UUID) -> User | None:
        stmt = select(User).where(
            User.public_id == public_id, User.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        email: str,
        password_hash: str | None,
        display_name: str = "",
        is_superuser: bool = False,
    ) -> User:
        user = User(
            email=email,
            password_hash=password_hash,
            display_name=display_name,
            is_superuser=is_superuser,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def touch_login(self, user_id: int) -> None:
        user = await self.get_by_id(user_id)
        if user is not None:
            user.last_login_at = dt.datetime.now(tz=dt.UTC)
            await self._session.flush()
