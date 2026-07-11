"""API key service: mint/list/revoke/rotate."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import ActorKind, ScopeType
from kortex_core.models.api_key import ApiKey
from kortex_core.repositories.api_key_repo import ApiKeyRepository
from kortex_core.security.api_keys import generate_api_key
from kortex_core.security.principal import Principal
from kortex_core.services.access_control import AccessDeniedError


@dataclass(frozen=True, slots=True)
class MintedApiKey:
    """Result of minting a new key. ``plaintext`` must be returned to the user
    exactly once and never persisted.
    """

    plaintext: str
    api_key: ApiKey


class ApiKeyService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._repo = ApiKeyRepository(session, principal=principal)
        self._principal = principal

    async def mint(
        self,
        *,
        name: str,
        scopes: list[str],
        scope_type: ScopeType | None = None,
        scope_id: int | None = None,
        expires_in_days: int | None = None,
    ) -> MintedApiKey:
        # A scoped API key must not be able to mint a key broader than itself
        # (else a read-only key mints an unrestricted one). Users (empty
        # key_scopes) are unrestricted here; org scoping is enforced downstream.
        if (
            self._principal.actor_kind == ActorKind.API_KEY
            and self._principal.key_scopes
            and not set(scopes).issubset(self._principal.key_scopes)
        ):
            raise AccessDeniedError("cannot mint an api key with broader scopes than the caller")
        material = generate_api_key()
        expires_at = (
            dt.datetime.now(tz=dt.UTC) + dt.timedelta(days=expires_in_days)
            if expires_in_days
            else None
        )
        created_by = (
            self._principal.actor_id if self._principal.actor_kind.value == "user" else None
        )
        key = await self._repo.create(
            prefix=material.prefix,
            key_hash=material.secret_hash,
            name=name,
            scopes=scopes,
            scope_type=scope_type,
            scope_id=scope_id,
            expires_at=expires_at,
            created_by=created_by,
        )
        return MintedApiKey(plaintext=material.plaintext, api_key=key)

    async def list_(self) -> list[ApiKey]:
        return await self._repo.list_for_org()

    async def revoke(self, public_id: uuid.UUID) -> ApiKey | None:
        return await self._repo.revoke(public_id)
