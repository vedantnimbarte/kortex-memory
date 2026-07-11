"""Memory service: CRUD + linking + access bookkeeping."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import (
    MemoryKind,
    MemoryLinkType,
    MemorySource,
    MemoryTier,
    ScopeType,
    Sensitivity,
)
from kortex_core.embeddings.registry import get_embedder
from kortex_core.models.memory import Memory, MemoryLink
from kortex_core.repositories.memory_link_repo import MemoryLinkRepository
from kortex_core.repositories.memory_repo import MemoryRepository, ScopeFilter
from kortex_core.repositories.org_repo import OrgRepository
from kortex_core.security.plan_limits import QuotaExceededError, max_memories
from kortex_core.security.principal import Principal, ScopeRef
from kortex_core.services.access_control import AccessControl, ResourceRef
from kortex_core.services.access_control import AccessDeniedError as _AccessDenied


@dataclass(frozen=True, slots=True)
class CreateMemoryInput:
    scope_type: ScopeType
    scope_id: int
    body: str
    title: str = ""
    kind: MemoryKind = MemoryKind.FACT
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    source_type: MemorySource = MemorySource.MANUAL
    source_ref: dict | None = None
    importance: float = 0.5
    pinned: bool = False
    metadata: dict | None = None
    expires_at: dt.datetime | None = None


class MemoryService:
    """Stateless service. Builds repos lazily; commit is the caller's job."""

    def __init__(self, session: AsyncSession, principal: Principal):
        self._session = session
        self._principal = principal
        self._repo = MemoryRepository(session, principal=principal)
        self._links = MemoryLinkRepository(session, principal=principal)
        self._ac = AccessControl()
        # Plan-quota state, cached across a batch (e.g. git-log ingest) so we
        # don't re-query the org/count per created memory.
        self._org_plan: str | None = None
        self._mem_count: int | None = None

    def _require_scope(self, name: str) -> None:
        """Enforce API-key scopes (no-op for users, whose key_scopes is empty)."""
        if not self._principal.has_key_scope(name):
            raise _AccessDenied(f"api key missing required scope {name!r}")

    async def _enforce_memory_quota(self) -> None:
        """Reject creation past the org's plan cap. Unlimited plans skip the
        count query entirely; capped plans count once then track locally."""
        if self._org_plan is None:
            org = await OrgRepository(self._session, principal=self._principal).get_by_id(
                self._principal.org_id
            )
            self._org_plan = org.plan if org else "free"
        cap = max_memories(self._org_plan)
        if cap < 0:
            return  # unlimited
        if self._mem_count is None:
            self._mem_count = await self._repo.count_for_org(self._principal.org_id)
        if self._mem_count >= cap:
            raise QuotaExceededError(
                f"memory limit reached for the {self._org_plan} plan "
                f"({cap:,} memories). Upgrade your plan to store more."
            )
        self._mem_count += 1

    def _require_write(self, memory: Memory) -> None:
        scope = ScopeRef(type=ScopeType(memory.scope_type), id=memory.scope_id)
        if not self._ac.can_write(
            self._principal,
            ResourceRef(scope=scope, sensitivity=Sensitivity(memory.sensitivity)),
        ):
            raise _AccessDenied(f"cannot modify {memory.sensitivity} memory in {scope}")

    async def create(self, payload: CreateMemoryInput, *, embed_inline: bool = False) -> Memory:
        self._require_scope("write:memory")
        scope_ref = ScopeRef(type=payload.scope_type, id=payload.scope_id)
        if not self._ac.can_write(
            self._principal,
            ResourceRef(scope=scope_ref, sensitivity=payload.sensitivity),
        ):
            raise _AccessDenied(f"cannot write {payload.sensitivity.value} memory in {scope_ref}")
        await self._enforce_memory_quota()

        embedding: list[float] | None = None
        embedding_model: str | None = None
        if embed_inline:
            embedder = get_embedder()
            text = (payload.title + "\n" + payload.body).strip() or payload.body
            vectors = await embedder.embed([text])
            embedding = vectors[0]
            embedding_model = embedder.model_id

        return await self._repo.create(
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            body=payload.body,
            title=payload.title,
            kind=payload.kind,
            sensitivity=payload.sensitivity,
            source_type=payload.source_type,
            source_ref=payload.source_ref,
            importance=payload.importance,
            pinned=payload.pinned,
            metadata=payload.metadata,
            expires_at=payload.expires_at,
            embedding=embedding,
            embedding_model=embedding_model,
            created_by=(
                self._principal.actor_id if self._principal.actor_kind.value == "user" else None
            ),
        )

    async def get(self, public_id: uuid.UUID) -> Memory | None:
        self._require_scope("read:memory")
        memory = await self._repo.get_by_public_id(public_id)
        if memory is None:
            return None
        scope = ScopeRef(type=ScopeType(memory.scope_type), id=memory.scope_id)
        if not self._ac.can_read(
            self._principal,
            ResourceRef(scope=scope, sensitivity=Sensitivity(memory.sensitivity)),
        ):
            return None
        return memory

    async def list_(
        self,
        *,
        scope: ScopeFilter | None = None,
        tier: MemoryTier | None = None,
        kind: MemoryKind | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        self._require_scope("read:memory")
        # Cap results to the sensitivity the caller may read; without this a
        # VIEWER could read SECRET bodies via the list endpoint that GET-by-id
        # denies. Superusers are unbounded.
        max_sensitivity = None if self._principal.is_superuser else self._principal.max_sensitivity
        return await self._repo.list_(
            scope=scope,
            tier=tier,
            kind=kind,
            limit=limit,
            offset=offset,
            max_sensitivity=max_sensitivity,
        )

    async def update(
        self,
        public_id: uuid.UUID,
        *,
        title: str | None = None,
        body: str | None = None,
        kind: MemoryKind | None = None,
        sensitivity: Sensitivity | None = None,
        importance: float | None = None,
        metadata: dict | None = None,
    ) -> Memory | None:
        self._require_scope("write:memory")
        memory = await self._repo.get_by_public_id(public_id)
        if memory is None:
            return None
        self._require_write(memory)
        # Re-classifying to a higher tier requires write access at that tier too.
        if sensitivity is not None and not self._ac.can_write(
            self._principal,
            ResourceRef(
                scope=ScopeRef(type=ScopeType(memory.scope_type), id=memory.scope_id),
                sensitivity=sensitivity,
            ),
        ):
            raise _AccessDenied(f"cannot set sensitivity {sensitivity.value}")
        return await self._repo.update_fields(
            memory,
            title=title,
            body=body,
            kind=kind,
            sensitivity=sensitivity,
            importance=importance,
            metadata=metadata,
        )

    async def delete(self, public_id: uuid.UUID) -> bool:
        self._require_scope("write:memory")
        memory = await self._repo.get_by_public_id(public_id)
        if memory is None:
            return False
        self._require_write(memory)
        await self._repo.soft_delete(memory)
        return True

    async def set_pinned(self, public_id: uuid.UUID, pinned: bool) -> Memory | None:
        self._require_scope("write:memory")
        memory = await self._repo.get_by_public_id(public_id)
        if memory is None:
            return None
        self._require_write(memory)
        await self._repo.set_pinned(memory, pinned)
        return memory

    async def link(
        self,
        *,
        from_public_id: uuid.UUID,
        to_public_id: uuid.UUID,
        link_type: MemoryLinkType = MemoryLinkType.RELATED,
        weight: float = 1.0,
    ) -> MemoryLink | None:
        a = await self._repo.get_by_public_id(from_public_id)
        b = await self._repo.get_by_public_id(to_public_id)
        if a is None or b is None:
            return None
        return await self._links.link(
            from_memory_id=a.id,
            to_memory_id=b.id,
            link_type=link_type,
            weight=weight,
        )

    async def list_links(self, public_id: uuid.UUID) -> list[tuple[Memory, str]]:
        """Linked memories for a memory (either direction), each with its link
        type. Returns [] if the memory is missing or unreadable."""
        self._require_scope("read:memory")
        mem = await self._repo.get_by_public_id(public_id)
        if mem is None:
            return []
        out: list[tuple[Memory, str]] = []
        for link in await self._links.neighbors(mem.id):
            other_id = link.to_memory_id if link.from_memory_id == mem.id else link.from_memory_id
            other = await self._repo.get_by_id(other_id)
            if other is not None:
                out.append((other, link.link_type))
        return out

    async def unlink(
        self,
        *,
        from_public_id: uuid.UUID,
        to_public_id: uuid.UUID,
        link_type: MemoryLinkType,
    ) -> bool:
        a = await self._repo.get_by_public_id(from_public_id)
        b = await self._repo.get_by_public_id(to_public_id)
        if a is None or b is None:
            return False
        return await self._links.unlink(
            from_memory_id=a.id,
            to_memory_id=b.id,
            link_type=link_type,
        )

    async def record_access(self, ids: Sequence[int]) -> None:
        await self._repo.record_access(ids)
