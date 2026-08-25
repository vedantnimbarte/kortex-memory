"""Superuser-only admin endpoints.

Each handler dispatches the matching Celery task and returns the task id. We
don't await the result here — long-running operations belong to the worker
queue, not request handlers.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, status

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import forbidden
from kortex_api.schemas.common import APIModel

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class AdminTaskOut(APIModel):
    task: str
    task_id: str | None
    dispatched: bool
    detail: str | None = None


class ReindexIn(APIModel):
    batch_size: int = 64


class EmbedFailureOut(APIModel):
    public_id: str
    title: str
    attempts: int
    error: str | None
    failed_at: str


class QuarantinedOut(APIModel):
    """A memory withheld because low-trust content read as instructions.

    ``body_preview`` is truncated on purpose: the point of review is to decide
    whether the content is hostile, which does not require reproducing all of
    it into another log or console.
    """

    public_id: str
    title: str
    body_preview: str
    source_type: str
    reason: str
    quarantined_at: str


class IngestStatusOut(APIModel):
    """Write-path health. ``failed > 0`` means memories were accepted by the API
    but never became searchable."""

    pending: int
    failed: int
    ok: int
    oldest_pending_seconds: float
    max_attempts: int
    recent_failures: list[EmbedFailureOut]


def _dispatch(task_name: str, *args: Any) -> AdminTaskOut:
    try:
        from celery import current_app
    except ImportError:
        return AdminTaskOut(
            task=task_name,
            task_id=None,
            dispatched=False,
            detail="celery not installed",
        )
    try:
        async_result = current_app.send_task(task_name, args=list(args))
        return AdminTaskOut(task=task_name, task_id=async_result.id, dispatched=True)
    except Exception as e:
        return AdminTaskOut(task=task_name, task_id=None, dispatched=False, detail=str(e))


def _require_superuser(principal) -> None:
    if not principal.is_superuser:
        raise forbidden("superuser required")


@router.post(
    "/force_decay_tick",
    response_model=AdminTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def force_decay_tick(
    principal: PrincipalDep, _session: SessionDep, org_id: int | None = None
) -> AdminTaskOut:
    _require_superuser(principal)
    if org_id is not None:
        return _dispatch("kortex.decay.decay_tick_org", org_id)
    return _dispatch("kortex.decay.decay_tick")


@router.post(
    "/reindex_embeddings",
    response_model=AdminTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_embeddings(
    payload: ReindexIn, principal: PrincipalDep, _session: SessionDep
) -> AdminTaskOut:
    _require_superuser(principal)
    # Re-embedding is done by ``embed_pending`` once embeddings are cleared.
    # The full sweep is a one-shot SQL UPDATE we issue here, then we kick the
    # embed task once to start draining.
    from kortex_core.db.session import session_scope
    from sqlalchemy import text

    async with session_scope() as session:
        await session.execute(text("UPDATE memories SET embedding = NULL, embedding_model = NULL"))
    result = _dispatch("kortex.embedding.embed_pending")
    return AdminTaskOut(
        task=result.task,
        task_id=result.task_id,
        dispatched=result.dispatched,
        detail=f"cleared embeddings; batch_size={payload.batch_size}; "
        f"embed_pending will refill incrementally",
    )


@router.post(
    "/consolidate_tier",
    response_model=AdminTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def force_consolidate(
    principal: PrincipalDep, _session: SessionDep, org_id: int | None = None
) -> AdminTaskOut:
    _require_superuser(principal)
    if org_id is not None:
        return _dispatch("kortex.consolidate.consolidate_tier_org", org_id)
    return _dispatch("kortex.consolidate.consolidate_tier")


@router.get("/ingest-status", response_model=IngestStatusOut)
async def ingest_status(principal: PrincipalDep, session: SessionDep) -> IngestStatusOut:
    """Counts of memories that are searchable, still queued, or parked as failed.

    Scoped to the caller's org unless they are a superuser, so a tenant can
    check their own write path without seeing anyone else's.
    """
    from kortex_core.repositories.memory_repo import MemoryRepository
    from kortex_core.settings import get_settings

    repo = MemoryRepository(session, principal=principal)
    counts = await repo.embed_status_counts()
    failures = await repo.list_embed_failures(limit=20)
    return IngestStatusOut(
        pending=counts.pending,
        failed=counts.failed,
        ok=counts.ok,
        oldest_pending_seconds=counts.oldest_pending_seconds,
        max_attempts=get_settings().embed_max_attempts,
        recent_failures=[
            EmbedFailureOut(
                public_id=str(m.public_id),
                title=m.title,
                attempts=m.embed_attempts,
                error=m.embed_error,
                failed_at=m.embed_failed_at.isoformat() if m.embed_failed_at else "",
            )
            for m in failures
        ],
    )


@router.post(
    "/retry_embeddings",
    response_model=AdminTaskOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_embeddings(
    principal: PrincipalDep, _session: SessionDep, org_id: int | None = None
) -> AdminTaskOut:
    """Release parked memories so ``embed_pending`` picks them up again.

    Distinct from ``reindex_embeddings``, which throws away *every* vector: this
    only touches the ones that failed.
    """
    _require_superuser(principal)
    return _dispatch("kortex.embedding.retry_failed", org_id)


@router.get("/quarantine", response_model=list[QuarantinedOut])
async def list_quarantine(principal: PrincipalDep, session: SessionDep) -> list[QuarantinedOut]:
    """Memories withheld from retrieval pending review.

    Org-scoped for ordinary callers. Anything listed here was ingested from a
    low-trust source and matched a prompt-injection heuristic — it is stored,
    but no recall will surface it until it is released.
    """
    from kortex_core.repositories.memory_repo import MemoryRepository

    repo = MemoryRepository(session, principal=principal)
    return [
        QuarantinedOut(
            public_id=str(m.public_id),
            title=m.title,
            body_preview=m.body[:280],
            source_type=m.source_type,
            reason=m.quarantine_reason or "",
            quarantined_at=m.quarantined_at.isoformat() if m.quarantined_at else "",
        )
        for m in await repo.list_quarantined(limit=50)
    ]


@router.post("/quarantine/{public_id}/release", response_model=AdminTaskOut)
async def release_quarantine(
    public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> AdminTaskOut:
    """Let a reviewed memory back into retrieval.

    Deliberately one at a time and superuser-only: releasing in bulk is how a
    review step becomes a rubber stamp.
    """
    _require_superuser(principal)
    from kortex_core.repositories.memory_repo import MemoryRepository

    repo = MemoryRepository(session, principal=principal)
    memory = await repo.get_by_public_id(public_id)
    if memory is None or memory.quarantined_at is None:
        return AdminTaskOut(
            task="quarantine.release",
            task_id=None,
            dispatched=False,
            detail="no quarantined memory with that id",
        )
    await repo.release_quarantine(memory)
    await session.commit()
    return AdminTaskOut(
        task="quarantine.release",
        task_id=str(public_id),
        dispatched=True,
        detail="released into retrieval",
    )
