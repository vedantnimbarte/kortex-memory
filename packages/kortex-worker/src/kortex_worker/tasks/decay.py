"""Decay tick.

Every 6h we fan out one task per org. Each org task scores its non-pinned
memories with the configured ``DecayPolicy``, writes the new ``decay_score``,
applies short→mid promotions, hard-deletes short-tier rows past the cutoff,
and archives mid-tier rows past the cutoff.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from kortex_core.db.engine import close_engine
from kortex_core.db.session import session_scope
from kortex_core.db.types import ActorKind, MemoryTier
from kortex_core.repositories.memory_repo import MemoryRepository
from kortex_core.security.principal import Principal
from kortex_core.skills.decay_policy import DecayInputs, get_decay_policy
from kortex_core.telemetry.logging import get_logger
from kortex_core.telemetry.tracing import span

from kortex_worker.celery_app import celery_app

log = get_logger("kortex.worker.decay")


def _superuser(org_id: int = 0) -> Principal:
    return Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=org_id,
        is_superuser=True,
    )


async def _tick_one_org(org_id: int) -> dict[str, int]:
    policy = get_decay_policy()
    now = dt.datetime.now(tz=dt.UTC)
    promoted = scored = archived = deleted = 0
    async with session_scope() as session:
        repo = MemoryRepository(session, principal=_superuser(org_id))
        median = await repo.median_access_count(org_id)
        rows = await repo.iter_for_decay(org_id)
        for m in rows:
            decision = policy.evaluate(
                DecayInputs(
                    importance=m.importance,
                    access_count=m.access_count,
                    last_accessed_at=m.last_accessed_at,
                    created_at=m.created_at,
                    tier=MemoryTier(m.tier),
                    pinned=m.pinned,
                ),
                now=now,
                median_access_count=median,
            )
            scored += 1
            if decision.should_hard_delete:
                await repo.hard_delete(m.id)
                deleted += 1
                continue
            if decision.should_archive:
                # Archival is a tier nudge today; M9 promotes to S3 export.
                await repo.apply_decay(
                    m.id,
                    decay_score=decision.new_decay_score,
                    new_tier=MemoryTier.LONG.value,
                )
                archived += 1
                continue
            new_tier = (
                decision.new_tier.value if decision.new_tier is not None else None
            )
            if new_tier is not None:
                promoted += 1
            await repo.apply_decay(
                m.id, decay_score=decision.new_decay_score, new_tier=new_tier
            )
    return {
        "org_id": org_id,
        "scored": scored,
        "promoted": promoted,
        "archived": archived,
        "deleted": deleted,
    }


async def _tick_all() -> list[dict[str, int]]:
    async with session_scope() as session:
        repo = MemoryRepository(session, principal=_superuser())
        org_ids = await repo.list_orgs_with_memories()
    results: list[dict[str, int]] = []
    for org_id in org_ids:
        with span("kortex.decay.tick", org_id=org_id):
            results.append(await _tick_one_org(org_id))
    return results


@celery_app.task(name="kortex.decay.decay_tick", bind=False)
def decay_tick() -> list[dict[str, int]]:
    try:
        return asyncio.run(_tick_all())
    finally:
        try:
            asyncio.run(close_engine())
        except Exception:  # pragma: no cover - cleanup is best-effort
            pass


@celery_app.task(name="kortex.decay.decay_tick_org", bind=False)
def decay_tick_org(org_id: int) -> dict[str, int]:
    try:
        return asyncio.run(_tick_one_org(int(org_id)))
    finally:
        try:
            asyncio.run(close_engine())
        except Exception:  # pragma: no cover
            pass
