"""Attachment + attachment_chunk repositories."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text, update

from kortex_core.db.types import AttachmentStatus, ScopeType, Sensitivity
from kortex_core.models.attachment import Attachment, AttachmentChunk
from kortex_core.repositories.base import BaseRepository
from kortex_core.repositories.memory_repo import ScopeFilter
from kortex_core.retrieval.hybrid import rrf_fuse
from kortex_core.settings import get_settings


@dataclass(frozen=True, slots=True)
class AttachmentChunkHit:
    """One ranked attachment-chunk match (mirrors HybridSearchHit shape)."""

    chunk_id: int
    attachment_id: int
    attachment_public_id: str
    filename: str
    chunk_index: int
    content: str
    score: float


class AttachmentRepository(BaseRepository[Attachment]):
    model = Attachment

    async def create(
        self,
        *,
        scope_type: ScopeType,
        scope_id: int,
        filename: str,
        mime: str | None,
        s3_bucket: str,
        s3_key: str,
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
        size_bytes: int = 0,
        sha256: str | None = None,
        metadata: dict | None = None,
        created_by: int | None = None,
    ) -> Attachment:
        attachment = Attachment(
            org_id=self.principal.org_id,
            scope_type=scope_type.value,
            scope_id=scope_id,
            created_by=created_by,
            filename=filename,
            mime=mime,
            size_bytes=size_bytes,
            sha256=sha256,
            s3_bucket=s3_bucket,
            s3_key=s3_key,
            sensitivity=sensitivity.value,
            processing_status=AttachmentStatus.PENDING.value,
            metadata_=dict(metadata) if metadata else {},
        )
        self._session.add(attachment)
        await self._session.flush()
        return attachment

    async def get_by_id(self, attachment_id: int) -> Attachment | None:
        stmt = self.tenant_query().where(
            Attachment.id == attachment_id, Attachment.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_public_id(self, public_id: uuid.UUID) -> Attachment | None:
        stmt = self.tenant_query().where(
            Attachment.public_id == public_id, Attachment.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_(
        self,
        *,
        scope: ScopeFilter | None = None,
        status: AttachmentStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Attachment]:
        stmt = self.tenant_query().where(Attachment.deleted_at.is_(None))
        if scope:
            stmt = stmt.where(
                Attachment.scope_type == scope.scope_type.value,
                Attachment.scope_id == scope.scope_id,
            )
        if status:
            stmt = stmt.where(Attachment.processing_status == status.value)
        stmt = stmt.order_by(Attachment.created_at.desc()).limit(limit).offset(offset)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_pending(self, *, limit: int = 16) -> list[Attachment]:
        """Pull attachments needing processing — bypasses tenancy (worker)."""
        stmt = (
            self.tenant_query()
            .where(Attachment.deleted_at.is_(None))
            .where(
                Attachment.processing_status.in_(
                    [
                        AttachmentStatus.PENDING.value,
                        AttachmentStatus.PROCESSING.value,
                    ]
                )
            )
            .order_by(Attachment.created_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def mark_status(
        self,
        attachment_id: int,
        *,
        status: AttachmentStatus,
        error: str | None = None,
        sha256: str | None = None,
        size_bytes: int | None = None,
        mime: str | None = None,
    ) -> None:
        values: dict[str, object] = {"processing_status": status.value}
        if status == AttachmentStatus.READY:
            values["processed_at"] = dt.datetime.now(tz=dt.UTC)
            values["processing_error"] = None
        if status == AttachmentStatus.FAILED:
            values["processing_error"] = error
        if sha256 is not None:
            values["sha256"] = sha256
        if size_bytes is not None:
            values["size_bytes"] = size_bytes
        if mime is not None:
            values["mime"] = mime
        await self._session.execute(
            update(Attachment).where(Attachment.id == attachment_id).values(**values)
        )

    async def soft_delete(self, attachment: Attachment) -> None:
        attachment.deleted_at = dt.datetime.now(tz=dt.UTC)
        await self._session.flush()


class AttachmentChunkRepository(BaseRepository[AttachmentChunk]):
    model = AttachmentChunk

    async def insert_many(
        self,
        *,
        attachment_id: int,
        chunks: Sequence[tuple[int, str]],
        embeddings: Sequence[list[float] | None] | None = None,
        embedding_model: str | None = None,
    ) -> int:
        """Insert chunks; ``embeddings`` may be ``None`` for deferred embedding."""
        org_id = self.principal.org_id
        rows: list[AttachmentChunk] = []
        for i, (idx, content) in enumerate(chunks):
            vec = embeddings[i] if embeddings else None
            rows.append(
                AttachmentChunk(
                    org_id=org_id,
                    attachment_id=attachment_id,
                    chunk_index=idx,
                    content=content,
                    embedding=vec,
                    embedding_model=embedding_model if vec is not None else None,
                )
            )
        if not rows:
            return 0
        self._session.add_all(rows)
        await self._session.flush()
        return len(rows)

    async def delete_for_attachment(self, attachment_id: int) -> None:
        await self._session.execute(
            text(
                "DELETE FROM attachment_chunks WHERE attachment_id = :aid"
            ),
            {"aid": attachment_id},
        )

    async def hybrid_search(
        self,
        *,
        query: str,
        query_vector: list[float] | None,
        scopes: list[ScopeFilter] | None = None,
        max_sensitivity: Sensitivity = Sensitivity.SECRET,
        limit: int = 20,
    ) -> list[AttachmentChunkHit]:
        """Vector + BM25 over attachment chunks, fused via RRF.

        Sensitivity is bounded by the caller; scope filtering applies on the
        parent ``attachments`` row (chunks inherit the attachment's scope).
        """
        s = get_settings()
        principal = self.principal

        org_filter_sql = ""
        params: dict[str, object] = {}
        if not principal.is_superuser:
            org_filter_sql = "AND a.org_id = :org_id"
            params["org_id"] = principal.org_id

        scope_filter_sql = ""
        if scopes:
            placeholders = ", ".join(
                f"(:st_{i}, :sid_{i})" for i in range(len(scopes))
            )
            scope_filter_sql = (
                f"AND (a.scope_type, a.scope_id) IN ({placeholders})"
            )
            for i, sf in enumerate(scopes):
                params[f"st_{i}"] = sf.scope_type.value
                params[f"sid_{i}"] = sf.scope_id

        sensitivity_rank = {
            Sensitivity.PUBLIC.value: 1,
            Sensitivity.INTERNAL.value: 2,
            Sensitivity.CONFIDENTIAL.value: 3,
            Sensitivity.SECRET.value: 4,
        }
        max_rank = sensitivity_rank[max_sensitivity.value]
        sens_allowed = [
            v for v, r in sensitivity_rank.items() if r <= max_rank
        ]
        sens_placeholders = ", ".join(
            f":sens_{i}" for i in range(len(sens_allowed))
        )
        for i, v in enumerate(sens_allowed):
            params[f"sens_{i}"] = v

        kv = s.retrieval_top_k_vector
        kb = s.retrieval_top_k_bm25
        rrf = s.retrieval_rrf_k

        vector_ids: list[int] = []
        if query_vector is not None:
            v_sql = text(
                f"""
                SELECT c.id
                FROM attachment_chunks c
                JOIN attachments a ON a.id = c.attachment_id
                WHERE a.deleted_at IS NULL
                  AND c.embedding IS NOT NULL
                  AND a.sensitivity IN ({sens_placeholders})
                  {org_filter_sql}
                  {scope_filter_sql}
                ORDER BY c.embedding <=> CAST(:qv AS vector) ASC
                LIMIT :k_v
                """
            )
            rows = (
                await self._session.execute(
                    v_sql, {**params, "qv": str(query_vector), "k_v": kv}
                )
            ).all()
            vector_ids = [int(r[0]) for r in rows]

        b_sql = text(
            f"""
            SELECT c.id,
                   ts_rank_cd(c.tsv, plainto_tsquery('english', :q)) AS rank
            FROM attachment_chunks c
            JOIN attachments a ON a.id = c.attachment_id
            WHERE a.deleted_at IS NULL
              AND c.tsv @@ plainto_tsquery('english', :q)
              AND a.sensitivity IN ({sens_placeholders})
              {org_filter_sql}
              {scope_filter_sql}
            ORDER BY rank DESC
            LIMIT :k_b
            """
        )
        bm25_rows = (
            await self._session.execute(b_sql, {**params, "q": query, "k_b": kb})
        ).all()
        bm25_ids = [int(r[0]) for r in bm25_rows]

        if not vector_ids and not bm25_ids:
            return []

        rankings = [r for r in (vector_ids, bm25_ids) if r]
        scores = rrf_fuse(rankings, k=rrf)
        ordered_ids = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)
        keep_ids = ordered_ids[: max(limit * 2, limit)]

        if not keep_ids:
            return []

        rows_q = text(
            """
            SELECT c.id, c.attachment_id, a.public_id::text, a.filename,
                   c.chunk_index, c.content
            FROM attachment_chunks c
            JOIN attachments a ON a.id = c.attachment_id
            WHERE c.id = ANY(:ids)
            """
        )
        rows = (
            await self._session.execute(rows_q, {"ids": keep_ids})
        ).all()
        by_id = {int(r[0]): r for r in rows}

        hits: list[AttachmentChunkHit] = []
        for cid in ordered_ids:
            if cid not in by_id:
                continue
            r = by_id[cid]
            hits.append(
                AttachmentChunkHit(
                    chunk_id=int(r[0]),
                    attachment_id=int(r[1]),
                    attachment_public_id=str(r[2]),
                    filename=str(r[3]),
                    chunk_index=int(r[4]),
                    content=str(r[5]),
                    score=scores[cid],
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]
