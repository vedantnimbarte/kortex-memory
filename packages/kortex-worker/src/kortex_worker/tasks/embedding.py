"""Embedding tasks.

``embed_pending`` runs every 30s and finds memories whose embedding is missing
or stale (different from the configured model). It batches them by 64 and
writes back in one UPDATE per memory.
"""

from __future__ import annotations

import asyncio

from kortex_core.db.engine import close_engine
from kortex_core.db.session import session_scope
from kortex_core.db.types import ActorKind
from kortex_core.embeddings.protocol import EmbeddingError
from kortex_core.embeddings.registry import get_embedder
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


async def _embed_batch() -> int:
    s = get_settings()
    try:
        embedder = get_embedder()
    except (KeyError, EmbeddingError) as e:
        log.warning("embedder_unavailable", error=str(e))
        return 0

    async with session_scope() as session:
        repo = MemoryRepository(session, principal=_superuser())
        pending = await repo.list_pending_embedding(limit=s.embedder_batch_size)
        if not pending:
            return 0
        texts = [
            (m.title + "\n" + m.body).strip() if m.title else m.body
            for m in pending
        ]
        try:
            vectors = await embedder.embed(texts)
        except EmbeddingError as e:  # pragma: no cover - depends on adapter
            log.error("embed_failed", error=str(e))
            return 0
        for memory, vector in zip(pending, vectors, strict=True):
            await repo.set_embedding(memory.id, vector, embedder.model_id)
        log.info(
            "embed_batch_done", count=len(pending), model=embedder.model_id
        )
        return len(pending)


@celery_app.task(name="kortex.embedding.embed_pending", bind=False)
def embed_pending() -> int:
    try:
        result = asyncio.run(_embed_batch())
        return result
    finally:
        try:
            asyncio.run(close_engine())
        except Exception:  # pragma: no cover - cleanup is best-effort
            pass
