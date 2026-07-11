"""Superuser-only admin endpoints.

Each handler dispatches the matching Celery task and returns the task id. We
don't await the result here — long-running operations belong to the worker
queue, not request handlers.
"""

from __future__ import annotations

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
