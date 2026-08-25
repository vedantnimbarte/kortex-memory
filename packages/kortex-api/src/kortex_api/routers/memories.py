"""Memories router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from kortex_core.db.types import MemoryKind, MemoryTier, ScopeType
from kortex_core.repositories.memory_repo import ScopeFilter
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import not_found
from kortex_api.schemas.memory import (
    LinkedMemoryOut,
    MemoryBulkIn,
    MemoryBulkOut,
    MemoryIn,
    MemoryLinkIn,
    MemoryOut,
    MemoryUpdateIn,
)

router = APIRouter(prefix="/v1/memories", tags=["memories"])


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryIn,
    principal: PrincipalDep,
    session: SessionDep,
    embed_inline: bool = Query(default=False),
    force: bool = Query(
        default=False,
        description=(
            "Store the memory even when an identical one already exists in this "
            "scope. Off by default: a repeat write folds into the existing memory "
            "so both copies do not compete for space in every future recall."
        ),
    ),
) -> MemoryOut:
    svc = MemoryService(session, principal)
    result = await svc.write(
        CreateMemoryInput(
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
            confidence=payload.confidence,
        ),
        embed_inline=embed_inline,
        force=force,
    )
    await session.commit()
    out = MemoryOut.model_validate(result.memory)
    return out.model_copy(
        update={
            "deduped": result.deduped,
            "pii_flags": result.pii_flags,
        }
    )


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    principal: PrincipalDep,
    session: SessionDep,
    scope_type: ScopeType | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    tier: MemoryTier | None = Query(default=None),
    kind: MemoryKind | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[MemoryOut]:
    svc = MemoryService(session, principal)
    scope = (
        ScopeFilter(scope_type=scope_type, scope_id=scope_id)
        if scope_type and scope_id is not None
        else None
    )
    memories = await svc.list_(scope=scope, tier=tier, kind=kind, limit=limit, offset=offset)
    return [MemoryOut.model_validate(m) for m in memories]


@router.post("/bulk", response_model=MemoryBulkOut)
async def bulk_memories(
    payload: MemoryBulkIn, principal: PrincipalDep, session: SessionDep
) -> MemoryBulkOut:
    svc = MemoryService(session, principal)
    affected = await svc.bulk_apply(payload.action, payload.public_ids)
    await session.commit()
    return MemoryBulkOut(affected=affected)


@router.get("/{public_id}", response_model=MemoryOut)
async def get_memory(
    public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> MemoryOut:
    svc = MemoryService(session, principal)
    memory = await svc.get(public_id)
    if memory is None:
        raise not_found("memory not found")
    return MemoryOut.model_validate(memory)


@router.patch("/{public_id}", response_model=MemoryOut)
async def update_memory(
    public_id: uuid.UUID,
    payload: MemoryUpdateIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> MemoryOut:
    svc = MemoryService(session, principal)
    memory = await svc.update(
        public_id,
        title=payload.title,
        body=payload.body,
        kind=payload.kind,
        sensitivity=payload.sensitivity,
        importance=payload.importance,
        metadata=payload.metadata,
    )
    if memory is None:
        raise not_found("memory not found")
    await session.commit()
    return MemoryOut.model_validate(memory)


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> None:
    svc = MemoryService(session, principal)
    ok = await svc.delete(public_id)
    if not ok:
        raise not_found("memory not found")
    await session.commit()


@router.post("/{public_id}/pin", response_model=MemoryOut)
async def pin_memory(
    public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> MemoryOut:
    svc = MemoryService(session, principal)
    memory = await svc.set_pinned(public_id, True)
    if memory is None:
        raise not_found("memory not found")
    await session.commit()
    return MemoryOut.model_validate(memory)


@router.delete("/{public_id}/pin", response_model=MemoryOut)
async def unpin_memory(
    public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> MemoryOut:
    svc = MemoryService(session, principal)
    memory = await svc.set_pinned(public_id, False)
    if memory is None:
        raise not_found("memory not found")
    await session.commit()
    return MemoryOut.model_validate(memory)


@router.get("/{public_id}/links", response_model=list[LinkedMemoryOut])
async def list_memory_links(
    public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> list[LinkedMemoryOut]:
    svc = MemoryService(session, principal)
    return [
        LinkedMemoryOut(
            public_id=m.public_id,
            title=m.title,
            tier=m.tier,
            link_type=link_type,
        )
        for (m, link_type) in await svc.list_links(public_id)
    ]


@router.post("/{public_id}/links", status_code=status.HTTP_204_NO_CONTENT)
async def link_memories(
    public_id: uuid.UUID,
    payload: MemoryLinkIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> None:
    svc = MemoryService(session, principal)
    link = await svc.link(
        from_public_id=public_id,
        to_public_id=payload.to_public_id,
        link_type=payload.link_type,
        weight=payload.weight,
    )
    if link is None:
        raise not_found("memory not found")
    await session.commit()


@router.delete("/{public_id}/links/{to_public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_memories(
    public_id: uuid.UUID,
    to_public_id: uuid.UUID,
    payload: MemoryLinkIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> None:
    svc = MemoryService(session, principal)
    ok = await svc.unlink(
        from_public_id=public_id,
        to_public_id=to_public_id,
        link_type=payload.link_type,
    )
    if not ok:
        raise not_found("link not found")
    await session.commit()
