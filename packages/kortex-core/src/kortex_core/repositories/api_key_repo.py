"""API key repository."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select

from kortex_core.db.types import ScopeType
from kortex_core.models.api_key import ApiKey
from kortex_core.repositories.base import BaseRepository


class ApiKeyRepository(BaseRepository[ApiKey]):
    model = ApiKey

    async def get_active_by_prefix(self, prefix: str) -> ApiKey | None:
        """Used at auth time. Filters revoked + expired keys server-side."""
        now = dt.datetime.now(tz=dt.UTC)
        stmt = select(ApiKey).where(
            ApiKey.prefix == prefix,
            ApiKey.revoked_at.is_(None),
            (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_org(self) -> list[ApiKey]:
        stmt = self.tenant_query().order_by(ApiKey.created_at.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_by_public_id(self, public_id: uuid.UUID) -> ApiKey | None:
        stmt = self.tenant_query().where(ApiKey.public_id == public_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def revoke(self, public_id: uuid.UUID) -> ApiKey | None:
        key = await self.get_by_public_id(public_id)
        if key is None:
            return None
        if key.revoked_at is None:
            key.revoked_at = dt.datetime.now(tz=dt.UTC)
            await self._session.flush()
        return key

    async def create(
        self,
        *,
        prefix: str,
        key_hash: str,
        name: str,
        scopes: list[str],
        scope_type: ScopeType | None = None,
        scope_id: int | None = None,
        expires_at: dt.datetime | None = None,
        created_by: int | None = None,
    ) -> ApiKey:
        key = ApiKey(
            org_id=self.principal.org_id,
            prefix=prefix,
            key_hash=key_hash,
            name=name,
            scopes=scopes,
            scope_type=scope_type.value if scope_type else None,
            scope_id=scope_id,
            expires_at=expires_at,
            created_by=created_by,
        )
        self._session.add(key)
        await self._session.flush()
        return key

    async def touch_used(self, key: ApiKey) -> None:
        key.last_used_at = dt.datetime.now(tz=dt.UTC)
        await self._session.flush()
