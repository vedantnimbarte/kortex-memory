"""Memory repository: CRUD + hybrid_search."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select, text, update

from kortex_core.db.types import (
    MemoryKind,
    MemorySource,
    MemoryTier,
    ScopeType,
    Sensitivity,
)
from kortex_core.models.memory import Memory
from kortex_core.repositories.base import BaseRepository
from kortex_core.retrieval.hybrid import HybridSearchHit, rrf_fuse
from kortex_core.settings import get_settings


@dataclass(frozen=True, slots=True)
class ScopeFilter:
    scope_type: ScopeType
    scope_id: int


class MemoryRepository(BaseRepository[Memory]):
    model = Memory

    # ---- writes ----

    async def create(
        self,
        *,
        scope_type: ScopeType,
        scope_id: int,
        body: str,
        title: str = "",
        kind: MemoryKind = MemoryKind.FACT,
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
        source_type: MemorySource = MemorySource.MANUAL,
        source_ref: dict | None = None,
        importance: float = 0.5,
        pinned: bool = False,
        metadata: dict | None = None,
        expires_at: dt.datetime | None = None,
        embedding: list[float] | None = None,
        embedding_model: str | None = None,
        created_by: int | None = None,
    ) -> Memory:
        memory = Memory(
            org_id=self.principal.org_id,
            scope_type=scope_type.value,
            scope_id=scope_id,
            created_by=created_by,
            source_type=source_type.value,
            source_ref=source_ref,
            kind=kind.value,
            title=title,
            body=body,
            tier=MemoryTier.SHORT.value,
            sensitivity=sensitivity.value,
            importance=importance,
            pinned=pinned,
            embedding=embedding,
            embedding_model=embedding_model,
            metadata_=dict(metadata) if metadata else {},
            expires_at=expires_at,
        )
        self._session.add(memory)
        await self._session.flush()
        return memory

    async def get_by_public_id(self, public_id: uuid.UUID) -> Memory | None:
        stmt = self.tenant_query().where(
            Memory.public_id == public_id, Memory.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, memory_id: int) -> Memory | None:
        stmt = self.tenant_query().where(
            Memory.id == memory_id, Memory.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_(
        self,
        *,
        scope: ScopeFilter | None = None,
        tier: MemoryTier | None = None,
        kind: MemoryKind | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        stmt = self.tenant_query().where(Memory.deleted_at.is_(None))
        if scope:
            stmt = stmt.where(
                Memory.scope_type == scope.scope_type.value,
                Memory.scope_id == scope.scope_id,
            )
        if tier:
            stmt = stmt.where(Memory.tier == tier.value)
        if kind:
            stmt = stmt.where(Memory.kind == kind.value)
        stmt = stmt.order_by(Memory.created_at.desc()).limit(limit).offset(offset)
        return list((await self._session.execute(stmt)).scalars().all())

    async def soft_delete(self, memory: Memory) -> None:
        memory.deleted_at = dt.datetime.now(tz=dt.UTC)
        await self._session.flush()

    async def set_pinned(self, memory: Memory, pinned: bool) -> None:
        memory.pinned = pinned
        await self._session.flush()

    async def update_fields(
        self,
        memory: Memory,
        *,
        title: str | None = None,
        body: str | None = None,
        kind: MemoryKind | None = None,
        sensitivity: Sensitivity | None = None,
        importance: float | None = None,
        metadata: dict | None = None,
    ) -> Memory:
        if title is not None:
            memory.title = title
        if body is not None:
            memory.body = body
            # body changed → embedding stale; clear it so embed_pending picks it up
            memory.embedding = None
            memory.embedding_model = None
        if kind is not None:
            memory.kind = kind.value
        if sensitivity is not None:
            memory.sensitivity = sensitivity.value
        if importance is not None:
            memory.importance = importance
        if metadata is not None:
            memory.metadata_ = dict(metadata)
        await self._session.flush()
        return memory

    # ---- async embedding maintenance ----

    async def list_pending_embedding(self, *, limit: int = 64) -> list[Memory]:
        s = get_settings()
        stmt = (
            select(Memory)
            .where(Memory.deleted_at.is_(None))
            .where(
                (Memory.embedding.is_(None))
                | (Memory.embedding_model != s.embedder_model)
            )
            .order_by(Memory.created_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def set_embedding(
        self, memory_id: int, vector: list[float], model_id: str
    ) -> None:
        await self._session.execute(
            update(Memory)
            .where(Memory.id == memory_id)
            .values(embedding=vector, embedding_model=model_id)
        )

    async def record_access(self, memory_ids: Sequence[int]) -> None:
        if not memory_ids:
            return
        now = dt.datetime.now(tz=dt.UTC)
        await self._session.execute(
            update(Memory)
            .where(Memory.id.in_(list(memory_ids)))
            .values(
                access_count=Memory.access_count + 1,
                last_accessed_at=now,
            )
        )

    # ---- hybrid search ----

    async def hybrid_search(
        self,
        *,
        query: str,
        query_vector: list[float] | None,
        scopes: list[ScopeFilter] | None = None,
        max_sensitivity: Sensitivity = Sensitivity.SECRET,
        top_k_vector: int | None = None,
        top_k_bm25: int | None = None,
        rrf_k: int | None = None,
        limit: int = 20,
    ) -> list[HybridSearchHit]:
        """Hybrid retrieval: vector + BM25, fused via RRF, decay-weighted.

        ``query_vector`` may be ``None`` if the configured embedder is
        unavailable; in that case we fall back to BM25 only.
        """
        s = get_settings()
        kv = top_k_vector or s.retrieval_top_k_vector
        kb = top_k_bm25 or s.retrieval_top_k_bm25
        rrf = rrf_k or s.retrieval_rrf_k

        principal = self.principal
        org_filter_sql = ""
        params: dict[str, object] = {}
        if not principal.is_superuser:
            org_filter_sql = "AND m.org_id = :org_id"
            params["org_id"] = principal.org_id

        scope_filter_sql = ""
        if scopes:
            placeholders = ", ".join(
                f"(:st_{i}, :sid_{i})" for i in range(len(scopes))
            )
            scope_filter_sql = (
                f"AND (m.scope_type, m.scope_id) IN ({placeholders})"
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
            s_v for s_v, r in sensitivity_rank.items() if r <= max_rank
        ]
        sens_placeholders = ", ".join(
            f":sens_{i}" for i in range(len(sens_allowed))
        )
        for i, sv in enumerate(sens_allowed):
            params[f"sens_{i}"] = sv

        # --- vector ranking (if vector available) ---
        vector_ids: list[int] = []
        if query_vector is not None:
            v_sql = text(
                f"""
                SELECT m.id, m.embedding <=> CAST(:qv AS vector) AS distance
                FROM memories m
                WHERE m.deleted_at IS NULL
                  AND m.embedding IS NOT NULL
                  AND m.sensitivity IN ({sens_placeholders})
                  {org_filter_sql}
                  {scope_filter_sql}
                ORDER BY m.embedding <=> CAST(:qv AS vector) ASC
                LIMIT :k_v
                """
            )
            vparams = {**params, "qv": str(query_vector), "k_v": kv}
            rows = (await self._session.execute(v_sql, vparams)).all()
            vector_ids = [int(r[0]) for r in rows]

        # --- BM25-style ranking ---
        b_sql = text(
            f"""
            SELECT m.id,
                   ts_rank_cd(m.tsv, plainto_tsquery('english', :q)) AS rank
            FROM memories m
            WHERE m.deleted_at IS NULL
              AND m.tsv @@ plainto_tsquery('english', :q)
              AND m.sensitivity IN ({sens_placeholders})
              {org_filter_sql}
              {scope_filter_sql}
            ORDER BY rank DESC
            LIMIT :k_b
            """
        )
        bparams = {**params, "q": query, "k_b": kb}
        bm25_rows = (await self._session.execute(b_sql, bparams)).all()
        bm25_ids = [int(r[0]) for r in bm25_rows]

        if not vector_ids and not bm25_ids:
            return []

        # --- fuse ---
        candidate_set = set(vector_ids) | set(bm25_ids)

        # We need to know which candidates are pinned to apply the floor.
        pinned_q = text(
            "SELECT id FROM memories WHERE id = ANY(:ids) AND pinned = true"
        )
        pinned_rows = (
            await self._session.execute(pinned_q, {"ids": list(candidate_set)})
        ).all()
        pinned: set[int] = {int(r[0]) for r in pinned_rows}

        rankings = [r for r in (vector_ids, bm25_ids) if r]
        scores = rrf_fuse(rankings, k=rrf, pinned=pinned)

        # Pull memory rows to return (in score order) and apply decay multiplier.
        ordered_ids = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)
        keep_ids = ordered_ids[: max(limit * 2, limit)]

        if not keep_ids:
            return []

        rows_q = text(
            """
            SELECT id, public_id::text, title, body, tier, sensitivity,
                   importance, decay_score, pinned
            FROM memories
            WHERE id = ANY(:ids)
            """
        )
        rows = (await self._session.execute(rows_q, {"ids": keep_ids})).all()
        rows_by_id = {int(r[0]): r for r in rows}

        # Score = RRF * (0.5 + 0.5 * decay_score) so decay nudges but doesn't dominate.
        hits: list[HybridSearchHit] = []
        for mid in ordered_ids:
            if mid not in rows_by_id:
                continue
            r = rows_by_id[mid]
            decay_mult = 0.5 + 0.5 * float(r[7])
            hit = HybridSearchHit(
                memory_id=int(r[0]),
                public_id=str(r[1]),
                title=str(r[2]),
                body=str(r[3]),
                tier=str(r[4]),
                sensitivity=str(r[5]),
                importance=float(r[6]),
                decay_score=float(r[7]),
                pinned=bool(r[8]),
                score=scores[mid] * decay_mult,
            )
            hits.append(hit)

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]
