"""Memory repository: CRUD + hybrid_search."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, select, text, update

from kortex_core.db.types import (
    MemoryKind,
    MemorySource,
    MemoryTier,
    ReviewStatus,
    ScopeType,
    Sensitivity,
)
from kortex_core.embeddings.retry import decide_retry
from kortex_core.models.memory import Memory
from kortex_core.repositories.base import BaseRepository
from kortex_core.retrieval.hybrid import HybridSearchHit, rrf_fuse
from kortex_core.retrieval.text_search import DEFAULT_TS_CONFIG, config_for_scopes
from kortex_core.settings import get_settings

_SENSITIVITY_RANK = {
    Sensitivity.PUBLIC.value: 1,
    Sensitivity.INTERNAL.value: 2,
    Sensitivity.CONFIDENTIAL.value: 3,
    Sensitivity.SECRET.value: 4,
}


def _sensitivities_up_to(max_sensitivity: Sensitivity) -> list[str]:
    """String values at or below ``max_sensitivity`` (for read-cap filtering)."""
    max_rank = _SENSITIVITY_RANK[max_sensitivity.value]
    return [v for v, r in _SENSITIVITY_RANK.items() if r <= max_rank]


@dataclass(frozen=True, slots=True)
class ScopeFilter:
    scope_type: ScopeType
    scope_id: int


@dataclass(frozen=True, slots=True)
class EmbedStatus:
    """Write-path health: is anything stuck between `remember` and searchable?"""

    pending: int
    failed: int
    ok: int
    oldest_pending_seconds: float


@dataclass(frozen=True, slots=True)
class MemoryAnalytics:
    """Org-wide (or scope-wide) aggregates for the dashboard. All counts are
    computed in SQL over the full live set, not a sampled page."""

    count: int
    pinned: int
    avg_decay: float
    total_access: int
    by_tier: list[tuple[str, int]]
    by_kind: list[tuple[str, int]]
    by_sensitivity: list[tuple[str, int]]
    decay_health: tuple[int, int, int]  # (healthy >= .66, aging >= .33, faded)
    top_accessed: list[Memory]
    timeline: list[int]  # per-day new-memory counts, oldest→newest, len == days


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
        content_hash: str | None = None,
        trust: str = "medium",
        pii_flags: dict | None = None,
        review_status: str = "approved",
        review_reason: str | None = None,
        confidence: float | None = None,
        ts_config: str = DEFAULT_TS_CONFIG,
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
            content_hash=content_hash,
            trust=trust,
            pii_flags=dict(pii_flags) if pii_flags else {},
            review_status=review_status,
            review_reason=review_reason,
            confidence=confidence,
            ts_config=ts_config,
        )
        self._session.add(memory)
        await self._session.flush()
        return memory

    async def get_by_public_id(self, public_id: uuid.UUID) -> Memory | None:
        stmt = self.tenant_query().where(Memory.public_id == public_id, Memory.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, memory_id: int) -> Memory | None:
        stmt = self.tenant_query().where(Memory.id == memory_id, Memory.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count_for_org(self, org_id: int) -> int:
        """Live (non-deleted) memory count for an org — drives plan quotas."""
        stmt = (
            select(func.count())
            .select_from(Memory)
            .where(Memory.org_id == org_id, Memory.deleted_at.is_(None))
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def analytics(
        self,
        *,
        now: dt.datetime,
        scope: ScopeFilter | None = None,
        max_sensitivity: Sensitivity | None = None,
        days: int = 14,
        top_n: int = 5,
    ) -> MemoryAnalytics:
        """Compute dashboard aggregates in SQL over the whole live set.

        ``max_sensitivity`` caps rows to what the caller may read (mirrors
        :meth:`list_`); ``None`` means unbounded (superuser).
        """
        conds: list[ColumnElement[bool]] = [Memory.deleted_at.is_(None)]
        if scope:
            conds += [
                Memory.scope_type == scope.scope_type.value,
                Memory.scope_id == scope.scope_id,
            ]
        if max_sensitivity is not None:
            conds.append(Memory.sensitivity.in_(_sensitivities_up_to(max_sensitivity)))

        def base(*cols: Any) -> Select[Any]:
            return self.tenant_query(*cols).where(*conds)

        # Scalars + decay-health buckets in a single pass.
        row = (
            await self._session.execute(
                base(
                    func.count(),
                    func.count().filter(Memory.pinned.is_(True)),
                    func.coalesce(func.avg(Memory.decay_score), 0.0),
                    func.coalesce(func.sum(Memory.access_count), 0),
                    func.count().filter(Memory.decay_score >= 0.66),
                    func.count().filter(
                        and_(Memory.decay_score >= 0.33, Memory.decay_score < 0.66)
                    ),
                    func.count().filter(Memory.decay_score < 0.33),
                )
            )
        ).one()

        async def group(col: Any) -> list[tuple[str, int]]:
            rows = (await self._session.execute(base(col, func.count()).group_by(col))).all()
            return [(str(k), int(v)) for k, v in rows]

        by_tier = await group(Memory.tier)
        by_kind = await group(Memory.kind)
        by_sensitivity = await group(Memory.sensitivity)

        # Timeline: UTC day buckets, oldest→newest. Bucket in SQL (UTC), then
        # fill missing days with zero so the array is always length `days`.
        utc_midnight = dt.datetime(now.year, now.month, now.day, tzinfo=dt.UTC)
        start = utc_midnight - dt.timedelta(days=days - 1)
        day_col = func.date_trunc("day", func.timezone("UTC", Memory.created_at))
        day_rows = (
            await self._session.execute(
                base(day_col, func.count()).where(Memory.created_at >= start).group_by(day_col)
            )
        ).all()
        counts_by_day = {d.date(): int(c) for d, c in day_rows}
        timeline = [
            counts_by_day.get((start + dt.timedelta(days=i)).date(), 0) for i in range(days)
        ]

        top_stmt = base(Memory).order_by(Memory.access_count.desc()).limit(top_n)
        top_accessed = list((await self._session.execute(top_stmt)).scalars().all())

        return MemoryAnalytics(
            count=int(row[0]),
            pinned=int(row[1]),
            avg_decay=float(row[2]),
            total_access=int(row[3]),
            by_tier=by_tier,
            by_kind=by_kind,
            by_sensitivity=by_sensitivity,
            decay_health=(int(row[4]), int(row[5]), int(row[6])),
            top_accessed=top_accessed,
            timeline=timeline,
        )

    async def list_(
        self,
        *,
        scope: ScopeFilter | None = None,
        tier: MemoryTier | None = None,
        kind: MemoryKind | None = None,
        limit: int = 50,
        offset: int = 0,
        max_sensitivity: Sensitivity | None = None,
    ) -> list[Memory]:
        stmt = (
            self.tenant_query()
            .where(Memory.deleted_at.is_(None))
            .where(Memory.review_status == ReviewStatus.APPROVED.value)
        )
        if scope:
            stmt = stmt.where(
                Memory.scope_type == scope.scope_type.value,
                Memory.scope_id == scope.scope_id,
            )
        if tier:
            stmt = stmt.where(Memory.tier == tier.value)
        if kind:
            stmt = stmt.where(Memory.kind == kind.value)
        if max_sensitivity is not None:
            stmt = stmt.where(Memory.sensitivity.in_(_sensitivities_up_to(max_sensitivity)))
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
        """Memories eligible for an embedding attempt right now.

        Excludes the two states that would otherwise spin forever: memories
        parked after exhausting their retries, and memories still inside their
        backoff window.
        """
        s = get_settings()
        now = dt.datetime.now(tz=dt.UTC)
        stmt = (
            self.tenant_query()
            .where(Memory.deleted_at.is_(None))
            .where((Memory.embedding.is_(None)) | (Memory.embedding_model != s.embedder_model))
            .where(Memory.embed_failed_at.is_(None))
            .where((Memory.embed_next_attempt_at.is_(None)) | (Memory.embed_next_attempt_at <= now))
            .order_by(Memory.created_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def set_embedding(self, memory_id: int, vector: list[float], model_id: str) -> None:
        """Record a successful embedding, clearing any prior failure state."""
        await self._session.execute(
            update(Memory)
            .where(Memory.id == memory_id)
            .values(
                embedding=vector,
                embedding_model=model_id,
                embed_attempts=0,
                embed_error=None,
                embed_failed_at=None,
                embed_next_attempt_at=None,
            )
        )

    async def record_embed_failure(
        self,
        memory_ids: Sequence[int],
        *,
        error: str,
        max_attempts: int,
        retry_base_seconds: int,
    ) -> int:
        """Count an attempt against each memory, scheduling a retry or parking it.

        Returns how many crossed into the failed state on this call — the number
        worth alerting on, as opposed to the ones still being retried.
        """
        if not memory_ids:
            return 0
        now = dt.datetime.now(tz=dt.UTC)
        ids = list(memory_ids)
        rows = await self.list_by_ids(ids)
        failed = 0
        for memory in rows:
            decision = decide_retry(
                memory.embed_attempts,
                max_attempts=max_attempts,
                retry_base_seconds=retry_base_seconds,
                now=now,
            )
            values: dict[str, Any] = {
                "embed_attempts": decision.attempts,
                "embed_error": error[:2000],
                "embed_next_attempt_at": decision.next_attempt_at,
            }
            if decision.parked:
                values["embed_failed_at"] = now
                failed += 1
            await self._session.execute(
                update(Memory).where(Memory.id == memory.id).values(**values)
            )
        return failed

    async def reset_embed_failures(self, *, org_id: int | None = None) -> int:
        """Requeue parked memories. Returns how many were released.

        Selects through ``tenant_query`` first rather than issuing a bare
        UPDATE, so the org boundary comes from the same chokepoint as every
        other read instead of a second hand-written filter.
        """
        select_stmt = (
            self.tenant_query(Memory.id)
            .where(Memory.deleted_at.is_(None))
            .where(Memory.embed_failed_at.is_not(None))
        )
        if org_id is not None:
            select_stmt = select_stmt.where(Memory.org_id == org_id)
        ids = [int(row[0]) for row in (await self._session.execute(select_stmt)).all()]
        if not ids:
            return 0
        await self._session.execute(
            update(Memory)
            .where(Memory.id.in_(ids))
            .values(
                embed_attempts=0,
                embed_error=None,
                embed_failed_at=None,
                embed_next_attempt_at=None,
            )
        )
        return len(ids)

    async def embed_status_counts(self) -> EmbedStatus:
        """One aggregate pass for the ingest-status endpoint and the gauges.

        Org-scoped for ordinary principals: a tenant checking their own write
        path must not learn how much of everyone else's is stuck. The metrics
        exporter passes a superuser principal to get the fleet-wide totals.
        """
        s = get_settings()
        params: dict[str, object] = {"model": s.embedder_model}
        org_filter = ""
        if not self.principal.is_superuser:
            org_filter = "AND org_id = :org_id"
            params["org_id"] = self.principal.org_id
        row = (
            await self._session.execute(
                text(
                    f"""
                    SELECT
                      count(*) FILTER (
                        WHERE embedding IS NULL AND embed_failed_at IS NULL
                      ) AS pending,
                      count(*) FILTER (WHERE embed_failed_at IS NOT NULL) AS failed,
                      count(*) FILTER (
                        WHERE embedding IS NOT NULL AND embedding_model = :model
                      ) AS ok,
                      -- FILTER binds to the aggregate itself; wrapping the
                      -- aggregate in EXTRACT first makes it a syntax error.
                      COALESCE(EXTRACT(EPOCH FROM (now() - min(created_at) FILTER (
                        WHERE embedding IS NULL AND embed_failed_at IS NULL
                      ))), 0) AS oldest_pending_seconds
                    FROM memories
                    WHERE deleted_at IS NULL
                      {org_filter}
                    """
                ),
                params,
            )
        ).one()
        return EmbedStatus(
            pending=int(row[0]),
            failed=int(row[1]),
            ok=int(row[2]),
            oldest_pending_seconds=float(row[3]),
        )

    async def list_embed_failures(self, *, limit: int = 20) -> list[Memory]:
        """The parked memories themselves, newest failure first."""
        stmt = (
            self.tenant_query()
            .where(Memory.deleted_at.is_(None))
            .where(Memory.embed_failed_at.is_not(None))
            .order_by(Memory.embed_failed_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

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

    # ---- decay / consolidation maintenance ----

    async def list_orgs_with_memories(self) -> list[int]:
        """Return distinct org ids that have non-deleted memories (worker fan-out)."""
        stmt = text("SELECT DISTINCT org_id FROM memories WHERE deleted_at IS NULL")
        rows = (await self._session.execute(stmt)).all()
        return [int(r[0]) for r in rows]

    async def median_access_count(self, org_id: int) -> int:
        """Approximate median (Postgres ``percentile_cont``) used to normalise decay."""
        stmt = text(
            "SELECT COALESCE("
            " percentile_cont(0.5) WITHIN GROUP (ORDER BY access_count)"
            " FILTER (WHERE org_id = :org_id AND deleted_at IS NULL), 1)"
        )
        row = (await self._session.execute(stmt, {"org_id": org_id})).first()
        if not row:
            return 1
        return int(row[0] or 1)

    async def iter_for_decay(self, org_id: int, *, batch_size: int = 500) -> Sequence[Memory]:
        """Pull memories for a single org so we can score them in Python.

        Pinned memories are skipped at the SQL level — the policy clamps them
        to 1.0 anyway and we don't want to take their row lock unnecessarily.
        Worker callers pass a superuser principal so ``tenant_query`` becomes
        a pure pass-through; the explicit ``org_id`` predicate is the actual
        scope.
        """
        stmt = (
            self.tenant_query()
            .where(Memory.org_id == org_id)
            .where(Memory.deleted_at.is_(None))
            .where(Memory.pinned.is_(False))
            .limit(batch_size)
            .order_by(Memory.id)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return list(rows)

    async def apply_decay(
        self,
        memory_id: int,
        *,
        decay_score: float,
        new_tier: str | None = None,
    ) -> None:
        values: dict[str, object] = {"decay_score": decay_score}
        if new_tier is not None:
            values["tier"] = new_tier
        await self._session.execute(update(Memory).where(Memory.id == memory_id).values(**values))

    async def reanalyse_scope(
        self,
        *,
        scope_type: ScopeType,
        scope_id: int,
        ts_config: str,
    ) -> None:
        """Re-stem every memory in a scope under a new configuration.

        Writing ``ts_config`` regenerates each row's ``tsv``, so this is what
        makes a configuration change apply to text that is already stored
        rather than only to future writes.

        ponytail: one UPDATE over the whole scope. Correct at any size but a
        long write on a large project -- move it to a worker task if corpora
        grow.
        """
        stmt = (
            update(Memory)
            .where(
                Memory.org_id == self.principal.org_id,
                Memory.scope_type == scope_type.value,
                Memory.scope_id == scope_id,
                Memory.deleted_at.is_(None),
            )
            .values(ts_config=ts_config)
        )
        await self._session.execute(stmt)

    # ---- governance ----

    async def list_pending_review(self, *, limit: int = 50, offset: int = 0) -> list[Memory]:
        """The review inbox, oldest first.

        Oldest first on purpose: a queue worked newest-first leaves its oldest
        items forever, and those are the ones that have been invisible to
        recall the longest.
        """
        stmt = (
            self.tenant_query()
            .where(Memory.deleted_at.is_(None))
            .where(Memory.review_status == ReviewStatus.PENDING.value)
            .order_by(Memory.created_at)
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_pending_review(self) -> int:
        stmt = (
            self.tenant_query(func.count(Memory.id))
            .where(Memory.deleted_at.is_(None))
            .where(Memory.review_status == ReviewStatus.PENDING.value)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def set_review_status(
        self,
        memory: Memory,
        *,
        status: ReviewStatus,
        reviewer_id: int | None,
    ) -> Memory:
        """Record a decision. Who and when are kept, not just the outcome —
        a review trail that cannot say who approved something is not a trail."""
        memory.review_status = status.value
        memory.reviewed_at = dt.datetime.now(tz=dt.UTC)
        memory.reviewed_by = reviewer_id
        await self._session.flush()
        return memory

    async def find_similar_for_review(self, memory: Memory, *, limit: int = 3) -> list[Memory]:
        """Approved memories in the same scope that look like this one.

        Gives the reviewer the context the decision actually needs: whether
        this is new, or the fourth restatement of something already stored.
        Falls back to keyword overlap when the memory has no embedding yet,
        which is the common case at review time.
        """
        if memory.embedding is not None:
            candidates = await self.list_conflict_candidates(
                memory, limit=limit, min_similarity=0.5
            )
            return [m for m, _ in candidates]
        terms = " ".join(memory.body.split()[:8])
        if not terms.strip():
            return []
        hits = await self.hybrid_search(
            query=terms,
            query_vector=None,
            scopes=[ScopeFilter(scope_type=ScopeType(memory.scope_type), scope_id=memory.scope_id)],
            limit=limit + 1,
        )
        ids = [h.memory_id for h in hits if h.memory_id != memory.id][:limit]
        return await self.list_by_ids(ids)

    # ---- metadata addressing ----

    async def find_by_metadata(
        self,
        *,
        scope_type: ScopeType,
        scope_id: int,
        key: str,
        value: str,
    ) -> Memory | None:
        """One memory in a scope whose metadata key equals ``value``.

        Used by the Claude memory-tool backend, where a path in metadata is the
        file's identity. Held-for-review memories are **included** on purpose:
        they are invisible to recall, but they still occupy their path, and a
        lookup that skipped them would let a second row be minted at the same
        address.
        """
        stmt = (
            self.tenant_query()
            .where(
                Memory.deleted_at.is_(None),
                Memory.scope_type == scope_type.value,
                Memory.scope_id == scope_id,
                Memory.metadata_[key].astext == value,
            )
            .order_by(Memory.id)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_metadata_key(
        self,
        *,
        scope_type: ScopeType,
        scope_id: int,
        key: str,
        limit: int = 1000,
    ) -> list[Memory]:
        """Every memory in a scope carrying ``key`` in its metadata.

        ponytail: no index on the JSONB key and a flat cap of 1000. Fine for a
        memory-tool directory, which is a handful of files by design -- add a
        GIN index on metadata if this is ever asked to page a real corpus.
        """
        stmt = (
            self.tenant_query()
            .where(
                Memory.deleted_at.is_(None),
                Memory.scope_type == scope_type.value,
                Memory.scope_id == scope_id,
                Memory.metadata_[key].astext.isnot(None),
            )
            .order_by(Memory.id)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ---- deduplication ----

    async def find_by_content_hash(
        self,
        *,
        scope_type: ScopeType,
        scope_id: int,
        content_hash: str,
    ) -> Memory | None:
        """The live memory in this scope with the same fingerprint, if any.

        Scoped rather than org-wide on purpose: the same sentence recorded
        against two different projects is two facts, not one, and folding them
        together would leak one project's context into the other's recall.
        """
        stmt = (
            self.tenant_query()
            .where(Memory.deleted_at.is_(None))
            .where(Memory.scope_type == scope_type.value)
            .where(Memory.scope_id == scope_id)
            .where(Memory.content_hash == content_hash)
            .order_by(Memory.created_at)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def record_duplicate(self, memory: Memory, *, metadata: dict | None = None) -> Memory:
        """Fold a repeat write into the memory that already holds it.

        The repeat is evidence the fact still matters, so it counts as an
        access — which is what feeds the decay score and keeps a re-remembered
        memory from fading. Metadata is merged rather than replaced: the
        duplicate may carry a new source reference worth keeping, and dropping
        the existing keys would lose provenance the survivor already had.
        """
        memory.access_count += 1
        memory.last_accessed_at = dt.datetime.now(tz=dt.UTC)
        if metadata:
            memory.metadata_ = {**(memory.metadata_ or {}), **metadata}
        await self._session.flush()
        return memory

    # ---- conflict detection ----

    async def list_pending_conflict_check(
        self,
        *,
        kinds: Sequence[MemoryKind],
        limit: int = 32,
    ) -> list[Memory]:
        """Embedded memories the conflict judge hasn't looked at yet.

        Ordered newest-first: a fresh contradiction is worth surfacing before a
        year-old one, and it keeps the initial backfill from starving live writes.
        """
        stmt = (
            self.tenant_query()
            .where(Memory.deleted_at.is_(None))
            .where(Memory.conflict_checked_at.is_(None))
            .where(Memory.embedding.is_not(None))
            .where(Memory.kind.in_([k.value for k in kinds]))
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def mark_conflict_checked(self, memory_ids: Sequence[int]) -> None:
        if not memory_ids:
            return
        await self._session.execute(
            update(Memory)
            .where(Memory.id.in_(list(memory_ids)))
            .values(conflict_checked_at=dt.datetime.now(tz=dt.UTC))
        )

    async def list_conflict_candidates(
        self,
        memory: Memory,
        *,
        limit: int = 5,
        min_similarity: float = 0.82,
    ) -> list[tuple[Memory, float]]:
        """Nearest neighbours that could plausibly conflict with ``memory``.

        Narrowed hard on purpose — same org, same scope, same kind — because
        every candidate costs an LLM judgement, and a fact only conflicts with
        another fact about the same thing. Returns ``(memory, similarity)`` with
        cosine similarity, highest first.
        """
        if memory.embedding is None:
            return []
        sql = text(
            """
            SELECT m.id, 1 - (m.embedding <=> CAST(:qv AS vector)) AS similarity
            FROM memories m
            WHERE m.deleted_at IS NULL
              AND m.review_status = 'approved'
              AND m.embedding IS NOT NULL
              AND m.org_id = :org_id
              AND m.scope_type = :scope_type
              AND m.scope_id = :scope_id
              AND m.kind = :kind
              AND m.id <> :self_id
            ORDER BY m.embedding <=> CAST(:qv AS vector) ASC
            LIMIT :limit
            """
        )
        rows = (
            await self._session.execute(
                sql,
                {
                    "qv": str(list(memory.embedding)),
                    "org_id": memory.org_id,
                    "scope_type": memory.scope_type,
                    "scope_id": memory.scope_id,
                    "kind": memory.kind,
                    "self_id": memory.id,
                    "limit": limit,
                },
            )
        ).all()
        scored = {int(r[0]): float(r[1]) for r in rows if float(r[1]) >= min_similarity}
        if not scored:
            return []
        by_id = {m.id: m for m in await self.list_by_ids(list(scored))}
        pairs = [(by_id[mid], sim) for mid, sim in scored.items() if mid in by_id]
        pairs.sort(key=lambda pair: pair[1], reverse=True)
        return pairs

    async def list_by_ids(self, memory_ids: Sequence[int]) -> list[Memory]:
        if not memory_ids:
            return []
        stmt = self.tenant_query().where(Memory.id.in_(list(memory_ids)))
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_consolidation(self, org_id: int, *, limit: int = 500) -> list[Memory]:
        """Mid-tier candidates for nightly clustering."""
        stmt = (
            self.tenant_query()
            .where(Memory.org_id == org_id)
            .where(Memory.deleted_at.is_(None))
            .where(Memory.pinned.is_(False))
            .where(Memory.tier == "mid")
            .where(Memory.embedding.is_not(None))
            .order_by(Memory.id)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

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

        The query is parsed with the analyser of the first project searched
        (see :mod:`kortex_core.retrieval.text_search`), so a French project
        is searched with French stemming rather than English.
        """
        s = get_settings()
        kv = top_k_vector or s.retrieval_top_k_vector
        kb = top_k_bm25 or s.retrieval_top_k_bm25
        rrf = rrf_k or s.retrieval_rrf_k

        principal = self.principal
        org_filter_sql = ""
        params: dict[str, object] = {
            "ts_config": await config_for_scopes(self._session, principal, scopes)
        }
        if not principal.is_superuser:
            org_filter_sql = "AND m.org_id = :org_id"
            params["org_id"] = principal.org_id

        scope_filter_sql = ""
        if scopes:
            placeholders = ", ".join(f"(:st_{i}, :sid_{i})" for i in range(len(scopes)))
            scope_filter_sql = f"AND (m.scope_type, m.scope_id) IN ({placeholders})"
            for i, sf in enumerate(scopes):
                params[f"st_{i}"] = sf.scope_type.value
                params[f"sid_{i}"] = sf.scope_id

        sens_allowed = _sensitivities_up_to(max_sensitivity)
        sens_placeholders = ", ".join(f":sens_{i}" for i in range(len(sens_allowed)))
        for i, sv in enumerate(sens_allowed):
            params[f"sens_{i}"] = sv

        # Governance filters (WU-2.4). Quarantined memories are withheld from
        # every retrieval path — the whole point is that stored injections stop
        # being re-injected — and a recall made at confidential/secret
        # sensitivity does not draw on content the system did not author.
        gov_filter_sql = "AND m.review_status = 'approved'"
        cfg = get_settings()
        if cfg.trust_filtering:
            # Imported here, not at module scope: kortex_core.skills pulls in
            # kortex_core.services, which imports this module back, so the
            # module-level version made `import memory_repo` fail whenever it
            # was the first kortex import in a process.
            from kortex_core.skills.trust_policy import trusts_allowed_for

            allowed_trust = trusts_allowed_for(max_sensitivity)
            if allowed_trust:
                trust_placeholders = ", ".join(f":trust_{i}" for i in range(len(allowed_trust)))
                gov_filter_sql += f" AND m.trust IN ({trust_placeholders})"
                for i, tv in enumerate(allowed_trust):
                    params[f"trust_{i}"] = tv

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
                  {gov_filter_sql}
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
        # ``CAST(:ts_config AS regconfig)`` and not ``:ts_config::regconfig``:
        # SQLAlchemy's bind-param regex skips a name followed by a colon, so
        # the postgres cast shorthand leaves the parameter unbound and the
        # statement fails to parse.
        b_sql = text(
            f"""
            SELECT m.id,
                   ts_rank_cd(m.tsv, plainto_tsquery(CAST(:ts_config AS regconfig), :q)) AS rank
            FROM memories m
            WHERE m.deleted_at IS NULL
              AND m.tsv @@ plainto_tsquery(CAST(:ts_config AS regconfig), :q)
              AND m.sensitivity IN ({sens_placeholders})
              {gov_filter_sql}
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
        pinned_q = text("SELECT id FROM memories WHERE id = ANY(:ids) AND pinned = true")
        pinned_rows = (await self._session.execute(pinned_q, {"ids": list(candidate_set)})).all()
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
