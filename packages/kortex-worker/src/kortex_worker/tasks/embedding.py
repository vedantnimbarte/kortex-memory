"""Embedding tasks.

``embed_pending`` runs every 30s and finds memories whose embedding is missing
or stale (different from the configured model), batches them, and writes the
vectors back.

**A failed embedding is never silently dropped.** The batch call is one API
round trip, so a single unembeddable input used to take the whole batch down
with it — and because the failure was only logged, those memories kept
``embedding IS NULL`` forever: absent from vector search, retried on every
tick, with nothing to tell the user. Now:

* a batch failure falls back to per-item embedding, so one poison input costs
  one memory instead of sixty-four;
* every failure increments ``embed_attempts``, records the reason, and
  schedules an exponential backoff;
* once attempts are exhausted the memory is parked (``embed_failed_at``) and
  surfaced via ``GET /v1/admin/ingest-status``, the ``kortex_embed_failed``
  gauge, and ``kortex doctor`` — rather than retried forever in silence.

Parked memories are released by ``kortex admin retry-embeddings``.
"""

from __future__ import annotations

import asyncio

from kortex_core.db.engine import close_engine
from kortex_core.db.session import session_scope
from kortex_core.db.types import ActorKind
from kortex_core.embeddings.protocol import Embedder, EmbeddingError
from kortex_core.embeddings.registry import get_embedder
from kortex_core.models.memory import Memory
from kortex_core.repositories.memory_repo import MemoryRepository
from kortex_core.security.principal import Principal
from kortex_core.settings import get_settings
from kortex_core.telemetry.logging import get_logger

from kortex_worker.celery_app import celery_app

log = get_logger("kortex.worker.embedding")


def _superuser() -> Principal:
    return Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=0,
        is_superuser=True,
    )


def _text_of(memory: Memory) -> str:
    return (memory.title + "\n" + memory.body).strip() if memory.title else memory.body


async def _embed_one_by_one(
    repo: MemoryRepository,
    embedder: Embedder,
    pending: list[Memory],
) -> tuple[int, int, int]:
    """Retry a failed batch per item. Returns (embedded, retrying, parked).

    The point of this path is isolation: whatever broke the batch should cost
    only the memories that actually caused it.
    """
    s = get_settings()
    embedded = 0
    retrying = 0
    parked = 0
    for memory in pending:
        try:
            vectors = await embedder.embed([_text_of(memory)])
        except EmbeddingError as e:
            failed = await repo.record_embed_failure(
                [memory.id],
                error=str(e),
                max_attempts=s.embed_max_attempts,
                retry_base_seconds=s.embed_retry_base_seconds,
            )
            parked += failed
            retrying += 1 - failed
            log.warning(
                "embed_item_failed",
                memory_id=memory.id,
                org_id=memory.org_id,
                attempts=memory.embed_attempts + 1,
                parked=bool(failed),
                error=str(e),
            )
            continue
        await repo.set_embedding(memory.id, vectors[0], embedder.model_id)
        embedded += 1
    return embedded, retrying, parked


async def _embed_batch() -> dict[str, int | str]:
    s = get_settings()
    try:
        embedder = get_embedder()
    except (KeyError, EmbeddingError) as e:
        # No embedder configured/loadable: not the memories' fault, so this must
        # not count against their retry budget.
        log.warning("embedder_unavailable", error=str(e))
        return {"embedded": 0, "skipped": "embedder_unavailable"}

    async with session_scope() as session:
        repo = MemoryRepository(session, principal=_superuser())
        pending = await repo.list_pending_embedding(limit=s.embedder_batch_size)
        if not pending:
            return {"embedded": 0, "skipped": "nothing_pending"}

        try:
            vectors = await embedder.embed([_text_of(m) for m in pending])
        except EmbeddingError as e:
            log.warning("embed_batch_failed_falling_back", count=len(pending), error=str(e))
            embedded, retrying, parked = await _embed_one_by_one(repo, embedder, pending)
            return {
                "embedded": embedded,
                "retrying": retrying,
                "parked": parked,
                "degraded": "per_item",
            }

        if len(vectors) != len(pending):
            # A provider that returns a short list would otherwise zip-truncate
            # and silently leave the tail unembedded — the exact failure this
            # module exists to prevent.
            log.error("embed_batch_length_mismatch", expected=len(pending), got=len(vectors))
            embedded, retrying, parked = await _embed_one_by_one(repo, embedder, pending)
            return {
                "embedded": embedded,
                "retrying": retrying,
                "parked": parked,
                "degraded": "length_mismatch",
            }

        for memory, vector in zip(pending, vectors, strict=True):
            await repo.set_embedding(memory.id, vector, embedder.model_id)
        log.info("embed_batch_done", count=len(pending), model=embedder.model_id)
        return {"embedded": len(pending), "model": embedder.model_id}


@celery_app.task(name="kortex.embedding.embed_pending", bind=False)
def embed_pending() -> dict[str, int | str]:
    try:
        return asyncio.run(_embed_batch())
    finally:
        try:
            asyncio.run(close_engine())
        except Exception:  # pragma: no cover - cleanup is best-effort
            pass


@celery_app.task(name="kortex.embedding.retry_failed", bind=False)
def retry_failed(org_id: int | None = None) -> dict[str, int | str]:
    """Release parked memories back into the queue (all orgs, or one)."""

    async def _run() -> dict[str, int | str]:
        async with session_scope() as session:
            repo = MemoryRepository(session, principal=_superuser())
            released = await repo.reset_embed_failures(org_id=org_id)
        log.info("embed_failures_reset", released=released, org_id=org_id)
        return {"released": released}

    try:
        return asyncio.run(_run())
    finally:
        try:
            asyncio.run(close_engine())
        except Exception:  # pragma: no cover - cleanup is best-effort
            pass
