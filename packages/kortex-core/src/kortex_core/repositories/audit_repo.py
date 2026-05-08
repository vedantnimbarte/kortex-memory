"""Audit log repository (append-only)."""

from __future__ import annotations

from typing import Any

from kortex_core.db.types import ActorKind
from kortex_core.models.audit import AuditLog
from kortex_core.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def append(
        self,
        *,
        actor_kind: ActorKind,
        actor_id: int | None,
        action: str,
        target_type: str | None = None,
        target_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        org_id: int | None = None,
    ) -> AuditLog:
        principal_org = self.principal.org_id if not self.principal.is_superuser else None
        effective_org = org_id if org_id is not None else principal_org
        if effective_org is None:
            raise ValueError("audit append requires an org_id (no principal org)")
        entry = AuditLog(
            org_id=effective_org,
            actor_kind=actor_kind.value,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_=dict(metadata) if metadata else {},
            ip=ip,
            user_agent=user_agent,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry
