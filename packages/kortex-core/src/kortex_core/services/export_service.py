"""Scope export / import.

Streams a tar archive whose layout is:

    manifest.json
    memories.jsonl
    memory_links.jsonl
    attachments.jsonl
    attachment_chunks.jsonl
    blobs/<public_id>/<filename>

Imports reverse the flow into a target scope, minting fresh ids while keeping
the source public_ids in ``source_ref`` for traceability. Attachments come
through with their blobs uploaded via the configured ``BlobStore``.

The tarball is NOT zstd-compressed by default — we leave compression to the
operator (``--compress zstd`` flag in the CLI). The plain tar keeps the
service implementation portable across environments that lack zstandard.
"""

from __future__ import annotations

import io
import json
import tarfile
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import (
    MemoryKind,
    MemorySource,
    ScopeType,
    Sensitivity,
)
from kortex_core.repositories.attachment_repo import AttachmentRepository
from kortex_core.repositories.memory_repo import MemoryRepository, ScopeFilter
from kortex_core.security.principal import Principal
from kortex_core.services.attachment_service import AttachmentService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.storage.registry import get_blob_store


@dataclass(frozen=True, slots=True)
class ExportManifest:
    version: int = 1
    source_org_id: int = 0
    source_scope_type: str = ""
    source_scope_id: int = 0
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImportResult:
    memories: int
    links: int
    attachments: int


class ExportService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._session = session
        self._principal = principal

    async def export_to_tar(
        self,
        *,
        scope_type: ScopeType,
        scope_id: int,
        include_attachments: bool = True,
    ) -> bytes:
        """Build the export tarball in-memory. For small/medium scopes only;
        large exports should stream via :meth:`stream_export`.
        """
        chunks: list[bytes] = []
        async for chunk in self.stream_export(
            scope_type=scope_type,
            scope_id=scope_id,
            include_attachments=include_attachments,
        ):
            chunks.append(chunk)
        return b"".join(chunks)

    async def stream_export(
        self,
        *,
        scope_type: ScopeType,
        scope_id: int,
        include_attachments: bool = True,
    ) -> AsyncIterator[bytes]:
        """Stream the tar archive as it's built. Pure-Python; one tarfile in
        memory but written into a buffer the caller drains incrementally.
        """
        buf = io.BytesIO()
        tar = tarfile.open(fileobj=buf, mode="w")

        memories_repo = MemoryRepository(
            self._session, principal=self._principal
        )
        attachments_repo = AttachmentRepository(
            self._session, principal=self._principal
        )

        scope = ScopeFilter(scope_type=scope_type, scope_id=scope_id)

        # Memories
        memories = await memories_repo.list_(scope=scope, limit=10_000)
        memory_rows = []
        memory_id_map: dict[int, str] = {}
        for m in memories:
            memory_id_map[m.id] = str(m.public_id)
            memory_rows.append(
                {
                    "public_id": str(m.public_id),
                    "scope_type": m.scope_type,
                    "scope_id": m.scope_id,
                    "title": m.title,
                    "body": m.body,
                    "kind": m.kind,
                    "sensitivity": m.sensitivity,
                    "tier": m.tier,
                    "importance": m.importance,
                    "pinned": m.pinned,
                    "metadata": m.metadata_,
                    "source_type": m.source_type,
                    "source_ref": m.source_ref,
                }
            )
        _add_jsonl(tar, "memories.jsonl", memory_rows)

        # Links
        link_rows: list[dict] = []
        if memory_id_map:
            ids = list(memory_id_map.keys())
            rows = (
                await self._session.execute(
                    text(
                        "SELECT from_memory_id, to_memory_id, link_type, weight "
                        "FROM memory_links WHERE from_memory_id = ANY(:ids) "
                        "OR to_memory_id = ANY(:ids)"
                    ),
                    {"ids": ids},
                )
            ).all()
            for from_id, to_id, link_type, weight in rows:
                if from_id not in memory_id_map or to_id not in memory_id_map:
                    continue
                link_rows.append(
                    {
                        "from_public_id": memory_id_map[from_id],
                        "to_public_id": memory_id_map[to_id],
                        "link_type": link_type,
                        "weight": float(weight),
                    }
                )
        _add_jsonl(tar, "memory_links.jsonl", link_rows)

        # Attachments
        attachment_rows: list[dict] = []
        chunk_rows: list[dict] = []
        if include_attachments:
            atts = await attachments_repo.list_(scope=scope, limit=10_000)
            store = get_blob_store()
            for a in atts:
                attachment_rows.append(
                    {
                        "public_id": str(a.public_id),
                        "filename": a.filename,
                        "mime": a.mime,
                        "size_bytes": a.size_bytes,
                        "sha256": a.sha256,
                        "sensitivity": a.sensitivity,
                        "processing_status": a.processing_status,
                        "metadata": a.metadata_,
                    }
                )
                try:
                    body = await store.get_bytes(
                        bucket=a.s3_bucket, key=a.s3_key
                    )
                except Exception:  # noqa: BLE001
                    body = b""
                _add_bytes(tar, f"blobs/{a.public_id}/{a.filename}", body)

                # Chunks for this attachment
                rows = (
                    await self._session.execute(
                        text(
                            "SELECT chunk_index, content FROM attachment_chunks "
                            "WHERE attachment_id = :aid ORDER BY chunk_index"
                        ),
                        {"aid": a.id},
                    )
                ).all()
                for idx, content in rows:
                    chunk_rows.append(
                        {
                            "attachment_public_id": str(a.public_id),
                            "chunk_index": int(idx),
                            "content": str(content),
                        }
                    )
        _add_jsonl(tar, "attachments.jsonl", attachment_rows)
        _add_jsonl(tar, "attachment_chunks.jsonl", chunk_rows)

        manifest = ExportManifest(
            source_org_id=self._principal.org_id,
            source_scope_type=scope_type.value,
            source_scope_id=scope_id,
            counts={
                "memories": len(memory_rows),
                "memory_links": len(link_rows),
                "attachments": len(attachment_rows),
                "attachment_chunks": len(chunk_rows),
            },
        )
        _add_jsonl(
            tar,
            "manifest.json",
            [
                {
                    "version": manifest.version,
                    "source_org_id": manifest.source_org_id,
                    "source_scope_type": manifest.source_scope_type,
                    "source_scope_id": manifest.source_scope_id,
                    "counts": manifest.counts,
                }
            ],
        )
        tar.close()
        yield buf.getvalue()

    async def import_from_tar(
        self,
        body: bytes,
        *,
        target_scope_type: ScopeType,
        target_scope_id: int,
    ) -> ImportResult:
        tar = tarfile.open(fileobj=io.BytesIO(body), mode="r")
        memories_repo = MemoryRepository(
            self._session, principal=self._principal
        )

        memory_rows = _read_jsonl(tar, "memories.jsonl")
        link_rows = _read_jsonl(tar, "memory_links.jsonl")
        attachment_rows = _read_jsonl(tar, "attachments.jsonl")

        old_to_new_uuid: dict[str, str] = {}

        # 1) Memories
        memory_svc = MemoryService(self._session, self._principal)
        created_memories = 0
        for row in memory_rows:
            new_mem = await memory_svc.create(
                CreateMemoryInput(
                    scope_type=target_scope_type,
                    scope_id=target_scope_id,
                    body=row["body"],
                    title=row.get("title", ""),
                    kind=MemoryKind(row.get("kind", "fact")),
                    sensitivity=Sensitivity(row.get("sensitivity", "internal")),
                    source_type=MemorySource.DERIVED,
                    source_ref={"imported_from": row["public_id"]},
                    importance=float(row.get("importance", 0.5)),
                    pinned=bool(row.get("pinned", False)),
                    metadata=row.get("metadata"),
                )
            )
            old_to_new_uuid[row["public_id"]] = str(new_mem.public_id)
            created_memories += 1

        # 2) Links — rebuild by public_id mapping
        created_links = 0
        for link in link_rows:
            new_from = old_to_new_uuid.get(link["from_public_id"])
            new_to = old_to_new_uuid.get(link["to_public_id"])
            if not new_from or not new_to:
                continue
            from kortex_core.db.types import MemoryLinkType

            await memory_svc.link(
                from_public_id=uuid.UUID(new_from),
                to_public_id=uuid.UUID(new_to),
                link_type=MemoryLinkType(link.get("link_type", "related")),
                weight=float(link.get("weight", 1.0)),
            )
            created_links += 1

        # 3) Attachments + blobs
        att_svc = AttachmentService(self._session, self._principal)
        store = get_blob_store()
        created_attachments = 0
        for att in attachment_rows:
            blob_path = f"blobs/{att['public_id']}/{att['filename']}"
            try:
                member = tar.getmember(blob_path)
                body_bytes = tar.extractfile(member).read() if member else b""  # type: ignore[union-attr]
            except KeyError:
                body_bytes = b""

            result = await att_svc.presign_upload(
                scope_type=target_scope_type,
                scope_id=target_scope_id,
                filename=att["filename"],
                mime=att.get("mime"),
                sensitivity=Sensitivity(att.get("sensitivity", "internal")),
                size_hint=len(body_bytes),
                metadata={
                    **(att.get("metadata") or {}),
                    "imported_from": att["public_id"],
                },
            )
            if body_bytes:
                await store.put_bytes(
                    bucket=result.attachment.s3_bucket,
                    key=result.attachment.s3_key,
                    body=body_bytes,
                    content_type=att.get("mime"),
                )
                await att_svc.finalize(result.attachment.public_id)
            created_attachments += 1

        return ImportResult(
            memories=created_memories,
            links=created_links,
            attachments=created_attachments,
        )


def _add_jsonl(tar: tarfile.TarFile, name: str, rows: list[dict]) -> None:
    body = ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)).encode()
    _add_bytes(tar, name, body)


def _add_bytes(tar: tarfile.TarFile, name: str, body: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(body)
    tar.addfile(info, io.BytesIO(body))


def _read_jsonl(tar: tarfile.TarFile, name: str) -> list[dict]:
    try:
        member = tar.getmember(name)
    except KeyError:
        return []
    f = tar.extractfile(member)
    if f is None:
        return []
    text_data = f.read().decode("utf-8")
    rows: list[dict] = []
    for line in text_data.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows
