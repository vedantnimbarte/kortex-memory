"""Mid-tier consolidation.

Once per day per org, cluster mid-tier memories by their stored vector and ask
the LLM consolidator to write one long-tier summary per cluster. Each summary
gets ``derived_from`` links back to its members; the members themselves are
nudged down by halving their decay_score so the new summary surfaces first.

HDBSCAN is optional (``kortex-core[clustering]``); when it isn't installed the
task no-ops with ``status="skipped:no_clusterer"``.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from kortex_core.db.engine import close_engine
from kortex_core.db.session import session_scope
from kortex_core.db.types import (
    ActorKind,
    MemoryKind,
    MemoryLinkType,
    MemorySource,
    MemoryTier,
    ScopeType,
    Sensitivity,
)
from kortex_core.repositories.memory_link_repo import MemoryLinkRepository
from kortex_core.repositories.memory_repo import MemoryRepository
from kortex_core.security.principal import Principal
from kortex_core.skills.consolidator import ClusterMember, get_consolidator
from kortex_core.telemetry.logging import get_logger
from kortex_core.telemetry.tracing import span

from kortex_worker.celery_app import celery_app

log = get_logger("kortex.worker.consolidate")


def _superuser(org_id: int = 0) -> Principal:
    return Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=org_id,
        is_superuser=True,
    )


def _cluster(vectors: list[list[float]]) -> list[int]:
    """Return per-row cluster labels (``-1`` is noise)."""
    try:
        import hdbscan
        import numpy as np
    except ImportError:
        return [-1] * len(vectors)
    if not vectors:
        return []
    arr = np.array(vectors, dtype="float32")
    model = hdbscan.HDBSCAN(min_cluster_size=3, metric="euclidean")
    labels = model.fit_predict(arr)
    return [int(label) for label in labels]


async def _consolidate_org(org_id: int) -> dict[str, int]:
    async with session_scope() as session:
        repo = MemoryRepository(session, principal=_superuser(org_id))
        links = MemoryLinkRepository(session, principal=_superuser(org_id))
        candidates = await repo.list_for_consolidation(org_id)

    if not candidates:
        return {"org_id": org_id, "clusters": 0, "summaries": 0, "skipped": "no_candidates"}

    try:
        vectors = [list(m.embedding) for m in candidates if m.embedding is not None]
    except TypeError:
        # ``embedding`` may be a pgvector ``Vector`` proxy — let it iterate.
        vectors = [list(m.embedding) for m in candidates if m.embedding is not None]
    labels = _cluster(vectors)
    if not labels or set(labels) == {-1}:
        return {"org_id": org_id, "clusters": 0, "summaries": 0, "skipped": "no_clusters"}

    groups: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        if label < 0:
            continue
        groups.setdefault(label, []).append(idx)

    consolidator = get_consolidator()
    summaries = 0
    async with session_scope() as session:
        repo = MemoryRepository(session, principal=_superuser(org_id))
        links = MemoryLinkRepository(session, principal=_superuser(org_id))
        for label, idxs in groups.items():
            cluster_members = [
                ClusterMember(
                    memory_id=candidates[i].id,
                    public_id=str(candidates[i].public_id),
                    title=candidates[i].title,
                    body=candidates[i].body,
                )
                for i in idxs
            ]
            with span("kortex.consolidate.cluster", org_id=org_id, label=label, size=len(idxs)):
                result = await consolidator.consolidate(cluster_members)
            if result is None:
                continue
            # Reference any cluster member's scope to host the new summary.
            anchor = candidates[idxs[0]]
            summary = await repo.create(
                scope_type=ScopeType(anchor.scope_type),
                scope_id=anchor.scope_id,
                body=result.body,
                title=result.title,
                kind=MemoryKind.SUMMARY,
                sensitivity=Sensitivity(anchor.sensitivity),
                source_type=MemorySource.DERIVED,
                importance=max(anchor.importance, 0.7),
            )
            # New summary lives in the long tier.
            await repo.apply_decay(
                summary.id, decay_score=1.0, new_tier=MemoryTier.LONG.value
            )
            for mid in result.derived_from_ids:
                await links.link(
                    from_memory_id=summary.id,
                    to_memory_id=mid,
                    link_type=MemoryLinkType.DERIVED_FROM,
                )
                # Dampen members so the summary surfaces in retrieval.
                source = next(c for c in candidates if c.id == mid)
                await repo.apply_decay(
                    source.id, decay_score=source.decay_score * 0.5
                )
            summaries += 1

    return {"org_id": org_id, "clusters": len(groups), "summaries": summaries}


async def _consolidate_all() -> list[dict[str, int]]:
    async with session_scope() as session:
        repo = MemoryRepository(session, principal=_superuser())
        orgs = await repo.list_orgs_with_memories()
    results: list[dict[str, int]] = []
    for org_id in orgs:
        results.append(await _consolidate_org(org_id))
    return results


@celery_app.task(name="kortex.consolidate.consolidate_tier", bind=False)
def consolidate_tier() -> list[dict[str, int]]:
    try:
        return asyncio.run(_consolidate_all())
    finally:
        try:
            asyncio.run(close_engine())
        except Exception:  # pragma: no cover
            pass


@celery_app.task(name="kortex.consolidate.consolidate_tier_org", bind=False)
def consolidate_tier_org(org_id: int) -> dict[str, int]:
    try:
        return asyncio.run(_consolidate_org(int(org_id)))
    finally:
        try:
            asyncio.run(close_engine())
        except Exception:  # pragma: no cover
            pass
