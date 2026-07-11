"""Attachment processing.

The ``process_attachment`` task takes one ``attachment_id``, downloads the
object from the blob store, extracts text, chunks it, embeds the chunks, and
flips the attachment to ``ready``. On failure it records the error and marks
the row ``failed`` so an operator (or the UI) can retry.
"""

from __future__ import annotations

import asyncio

from kortex_core.attachments.chunker import chunk_text
from kortex_core.attachments.extract import extract_text
from kortex_core.db.engine import close_engine
from kortex_core.db.session import session_scope
from kortex_core.db.types import ActorKind, AttachmentStatus
from kortex_core.embeddings.protocol import EmbeddingError
from kortex_core.embeddings.registry import get_embedder
from kortex_core.repositories.attachment_repo import (
    AttachmentChunkRepository,
    AttachmentRepository,
)
from kortex_core.security.principal import Principal
from kortex_core.settings import get_settings
from kortex_core.storage.registry import get_blob_store
from kortex_core.telemetry.logging import get_logger

from kortex_worker.celery_app import celery_app

log = get_logger("kortex.worker.attachment")


def _superuser() -> Principal:
    return Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=0,
        is_superuser=True,
    )


async def _process_one(attachment_id: int) -> str:
    s = get_settings()
    store = get_blob_store()

    async with session_scope() as session:
        repo = AttachmentRepository(session, principal=_superuser())
        chunks_repo = AttachmentChunkRepository(session, principal=_superuser())

        attachment = await repo.get_by_id(attachment_id)
        if attachment is None:
            return "missing"

        # Bind principal to the attachment's org so the chunk repo writes the
        # correct ``org_id`` and the tenancy check is satisfied.
        chunks_repo._principal = Principal(
            actor_id=0,
            actor_kind=ActorKind.SYSTEM,
            org_id=attachment.org_id,
            is_superuser=True,
        )

        try:
            body = await store.get_bytes(bucket=attachment.s3_bucket, key=attachment.s3_key)
            text = extract_text(body, mime=attachment.mime, filename=attachment.filename)
        except Exception as e:
            log.error(
                "attachment_extract_failed",
                attachment_id=attachment_id,
                error=str(e),
            )
            await repo.mark_status(attachment_id, status=AttachmentStatus.FAILED, error=str(e))
            return "failed"

        if not text.strip():
            await repo.mark_status(
                attachment_id,
                status=AttachmentStatus.FAILED,
                error="no extractable text",
            )
            return "empty"

        chunks = list(
            chunk_text(
                text,
                max_tokens=s.attachment_chunk_tokens,
                overlap_tokens=s.attachment_chunk_overlap,
            )
        )

        # Replace any prior chunks (idempotent reprocessing).
        await chunks_repo.delete_for_attachment(attachment_id)

        # Try to embed up-front; if the embedder isn't available, write chunks
        # without vectors and let ``embed_pending`` (M2) or a future
        # attachment-specific embed task fill them in.
        embedder = None
        try:
            embedder = get_embedder()
        except (KeyError, EmbeddingError) as e:
            log.warning("attachment_embedder_unavailable", error=str(e))

        if embedder is not None and chunks:
            try:
                vectors = await embedder.embed([c for _, c in chunks])
            except EmbeddingError as e:  # pragma: no cover - adapter-specific
                log.warning("attachment_embed_failed", error=str(e))
                vectors = None
            else:
                await chunks_repo.insert_many(
                    attachment_id=attachment_id,
                    chunks=chunks,
                    embeddings=vectors,
                    embedding_model=embedder.model_id,
                )
                await repo.mark_status(attachment_id, status=AttachmentStatus.READY)
                log.info(
                    "attachment_ready",
                    attachment_id=attachment_id,
                    chunks=len(chunks),
                )
                return "ready"
        # No embedder or embedding failed → still record chunks for BM25.
        await chunks_repo.insert_many(attachment_id=attachment_id, chunks=chunks)
        await repo.mark_status(attachment_id, status=AttachmentStatus.READY)
        log.info(
            "attachment_ready_no_embeddings",
            attachment_id=attachment_id,
            chunks=len(chunks),
        )
        return "ready_no_embeddings"


@celery_app.task(name="kortex.attachment.process_attachment", bind=False)
def process_attachment(attachment_id: int) -> str:
    try:
        return asyncio.run(_process_one(int(attachment_id)))
    finally:
        try:
            asyncio.run(close_engine())
        except Exception:  # pragma: no cover
            pass
