"""Attachment service: presign + finalize + processing handoff.

Upload flow (presign+finalize):

  1. Client calls ``presign_upload`` → server records the Attachment with
     ``processing_status='pending'`` and returns a presigned PUT URL.
  2. Client uploads the body directly to S3/MinIO (or, with the FS adapter,
     writes the file at the returned path).
  3. Client calls ``finalize`` with the attachment's public_id; service verifies
     the object exists (HEAD), updates size/sha/mime, queues processing.
  4. ``kortex_worker.tasks.attachments.process_attachment`` extracts text,
     chunks, embeds, marks ``ready``.

This split keeps large bodies off the API event loop and lets the API/MCP host
stay stateless.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import AttachmentStatus, ScopeType, Sensitivity
from kortex_core.models.attachment import Attachment
from kortex_core.repositories.attachment_repo import (
    AttachmentRepository,
)
from kortex_core.security.principal import Principal, ScopeRef
from kortex_core.services.access_control import (
    AccessControl,
    AccessDeniedError,
    ResourceRef,
)
from kortex_core.settings import get_settings
from kortex_core.storage.protocol import PresignedUpload
from kortex_core.storage.registry import get_blob_store


@dataclass(frozen=True, slots=True)
class PresignResult:
    attachment: Attachment
    upload: PresignedUpload


class AttachmentError(Exception):
    """Raised by AttachmentService for not-found / wrong-status / etc."""


def _build_key(*, org_id: int, scope_type: ScopeType, scope_id: int, filename: str) -> str:
    """Stable per-object key under the org's directory.

    ``filename`` is included for human readability; uniqueness comes from the
    UUID4 prefix so collisions can't happen across uploads.
    """
    safe = filename.replace("/", "_").replace("\\", "_")[:200]
    return f"orgs/{org_id}/{scope_type.value}/{scope_id}/{uuid.uuid4()}/{safe}"


class AttachmentService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._session = session
        self._principal = principal
        self._repo = AttachmentRepository(session, principal=principal)
        self._ac = AccessControl()

    def _require_scope(self, name: str) -> None:
        """Enforce API-key scopes (no-op for users, whose key_scopes is empty)."""
        if not self._principal.has_key_scope(name):
            raise AccessDeniedError(f"api key missing required scope {name!r}")

    async def presign_upload(
        self,
        *,
        scope_type: ScopeType,
        scope_id: int,
        filename: str,
        mime: str | None = None,
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
        size_hint: int | None = None,
        metadata: dict | None = None,
    ) -> PresignResult:
        self._require_scope("write:attachment")
        scope_ref = ScopeRef(type=scope_type, id=scope_id)
        if not self._ac.can_write(
            self._principal, ResourceRef(scope=scope_ref, sensitivity=sensitivity)
        ):
            raise AccessDeniedError(f"cannot write {sensitivity.value} attachment in {scope_ref}")

        s = get_settings()
        if size_hint and size_hint > s.attachment_max_bytes:
            raise AttachmentError(
                f"attachment exceeds max size ({size_hint} > {s.attachment_max_bytes})"
            )

        bucket = s.s3_bucket
        key = _build_key(
            org_id=self._principal.org_id,
            scope_type=scope_type,
            scope_id=scope_id,
            filename=filename,
        )

        attachment = await self._repo.create(
            scope_type=scope_type,
            scope_id=scope_id,
            filename=filename,
            mime=mime,
            s3_bucket=bucket,
            s3_key=key,
            sensitivity=sensitivity,
            size_bytes=size_hint or 0,
            metadata=metadata,
            created_by=(
                self._principal.actor_id if self._principal.actor_kind.value == "user" else None
            ),
        )

        store = get_blob_store()
        upload = await store.presign_put(
            bucket=bucket,
            key=key,
            content_type=mime,
            size_hint=size_hint,
        )
        return PresignResult(attachment=attachment, upload=upload)

    async def finalize(
        self,
        public_id: uuid.UUID,
        *,
        sha256: str | None = None,
        size_bytes: int | None = None,
        mime: str | None = None,
    ) -> Attachment | None:
        """Mark a pending attachment as ready for processing.

        The actual heavy work (download/extract/chunk/embed) runs in the
        ``process_attachment`` Celery task. We verify the object exists in S3
        so we never enqueue work for a missing upload, then flip status to
        ``processing`` so the worker picks it up.
        """
        self._require_scope("write:attachment")
        attachment = await self._repo.get_by_public_id(public_id)
        if attachment is None:
            return None
        if attachment.processing_status not in {
            AttachmentStatus.PENDING.value,
            AttachmentStatus.FAILED.value,
        }:
            return attachment  # already processed/processing

        store = get_blob_store()
        meta = await store.head(bucket=attachment.s3_bucket, key=attachment.s3_key)
        if meta is None:
            raise AttachmentError("object not found in blob store — finalize called before upload")

        # Enforce the real uploaded size (the presigned PUT can't be trusted —
        # size_hint is client-supplied and optional). Reject + delete oversize
        # blobs so a client can't PUT 50GB and have it accepted.
        s = get_settings()
        if meta.size_bytes > s.attachment_max_bytes:
            await store.delete(bucket=attachment.s3_bucket, key=attachment.s3_key)
            await self._repo.mark_status(
                attachment.id,
                status=AttachmentStatus.FAILED,
                error=f"upload exceeds max size ({meta.size_bytes} > {s.attachment_max_bytes})",
            )
            raise AttachmentError(
                f"attachment exceeds max size ({meta.size_bytes} > {s.attachment_max_bytes})"
            )

        await self._repo.mark_status(
            attachment.id,
            status=AttachmentStatus.PROCESSING,
            sha256=sha256 or meta.sha256,
            size_bytes=size_bytes or meta.size_bytes,
            mime=mime or meta.content_type or attachment.mime,
        )
        # Refresh in-memory copy.
        refreshed = await self._repo.get_by_id(attachment.id)
        assert refreshed is not None

        # Queue the worker task. Celery is optional at import time so the
        # core can be used without it (tests, REPL); the dispatch is wrapped.
        _enqueue_process(refreshed.id)
        return refreshed

    async def get(self, public_id: uuid.UUID) -> Attachment | None:
        self._require_scope("read:attachment")
        attachment = await self._repo.get_by_public_id(public_id)
        if attachment is None:
            return None
        if not self._ac.can_read(
            self._principal,
            ResourceRef(
                scope=ScopeRef(type=ScopeType(attachment.scope_type), id=attachment.scope_id),
                sensitivity=Sensitivity(attachment.sensitivity),
            ),
        ):
            return None
        return attachment

    async def list_(self, **kw) -> list[Attachment]:  # type: ignore[no-untyped-def]
        self._require_scope("read:attachment")
        # Cap to the sensitivity the caller may read (mirrors get()); without
        # this the list endpoint leaks SECRET attachments to a VIEWER.
        kw.setdefault(
            "max_sensitivity",
            None if self._principal.is_superuser else self._principal.max_sensitivity,
        )
        return await self._repo.list_(**kw)

    async def delete(self, public_id: uuid.UUID) -> bool:
        self._require_scope("write:attachment")
        attachment = await self._repo.get_by_public_id(public_id)
        if attachment is None:
            return False
        if not self._ac.can_write(
            self._principal,
            ResourceRef(
                scope=ScopeRef(type=ScopeType(attachment.scope_type), id=attachment.scope_id),
                sensitivity=Sensitivity(attachment.sensitivity),
            ),
        ):
            raise AccessDeniedError(f"cannot delete {attachment.sensitivity} attachment")
        await self._repo.soft_delete(attachment)
        # Worker can vacuum the blob later via `kortex.attachment.gc`; we keep
        # the row soft-deleted so processing-in-flight doesn't crash.
        return True

    async def mark_failed(self, attachment_id: int, error: str) -> None:
        await self._repo.mark_status(attachment_id, status=AttachmentStatus.FAILED, error=error)

    async def mark_ready(self, attachment_id: int) -> None:
        await self._repo.mark_status(attachment_id, status=AttachmentStatus.READY)

    @staticmethod
    def now() -> dt.datetime:
        return dt.datetime.now(tz=dt.UTC)


def _enqueue_process(attachment_id: int) -> None:
    """Dispatch ``process_attachment`` to Celery. Silent if the broker is down."""
    try:
        from celery import current_app
    except ImportError:  # pragma: no cover - celery is a worker dep
        return
    try:
        current_app.send_task("kortex.attachment.process_attachment", args=[attachment_id])
    except Exception:
        # The task can also be picked up by a periodic scan over pending rows
        # if the operator runs one — finalize is not the only entry point.
        pass
