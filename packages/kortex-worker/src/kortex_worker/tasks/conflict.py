"""Conflict detection.

Every minute, take the memories that have an embedding but have never been
judged, look up their nearest neighbours in the same scope, and ask the
conflict judge whether the new memory supersedes or contradicts any of them.
Verdicts become ``memory_links`` rows; recall surfaces them (see
:mod:`kortex_core.retrieval.conflicts`).

Why a separate task instead of doing this inline on write:

* Embedding is itself asynchronous — at ``POST /v1/memories`` time there is no
  vector to search with, so there are no candidates to compare against.
* It costs an LLM call. Keeping it off the write path means a slow or failing
  judge can never make `remember` slow or fail.

Only ``fact`` / ``preference`` / ``decision`` are judged. A procedure, a code
artifact, or an event does not contradict its neighbours in any useful sense,
and skipping them roughly halves the bill.
"""

from __future__ import annotations

import asyncio

from kortex_core.db.engine import close_engine
from kortex_core.db.session import session_scope
from kortex_core.db.types import ActorKind, MemoryKind, MemoryLinkType
from kortex_core.models.memory import Memory
from kortex_core.repositories.memory_link_repo import MemoryLinkRepository
from kortex_core.repositories.memory_repo import MemoryRepository
from kortex_core.security.principal import Principal
from kortex_core.security.quota import check_daily_quota
from kortex_core.settings import get_settings
from kortex_core.skills.conflict_judge import (
    ConflictCandidate,
    get_conflict_judge,
)
from kortex_core.telemetry.logging import get_logger
from kortex_core.telemetry.tracing import span

from kortex_worker.celery_app import celery_app

log = get_logger("kortex.worker.conflict")

JUDGED_KINDS = (MemoryKind.FACT, MemoryKind.PREFERENCE, MemoryKind.DECISION)

_RELATION_TO_LINK = {
    "supersedes": MemoryLinkType.SUPERSEDES,
    "contradicts": MemoryLinkType.CONTRADICTS,
}


def _superuser() -> Principal:
    return Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=0,
        is_superuser=True,
    )


def _as_candidate(memory: Memory) -> ConflictCandidate:
    return ConflictCandidate(
        memory_id=memory.id,
        public_id=str(memory.public_id),
        title=memory.title,
        body=memory.body,
        created_at=memory.created_at,
    )


async def _detect_batch() -> dict[str, int | str]:
    s = get_settings()
    if not s.conflict_detection:
        return {"checked": 0, "links": 0, "skipped": "disabled"}

    judge = get_conflict_judge()
    checked: list[int] = []
    quota_blocked = 0
    links_written = 0

    async with session_scope() as session:
        principal = _superuser()
        memories = MemoryRepository(session, principal=principal)
        links = MemoryLinkRepository(session, principal=principal)

        pending = await memories.list_pending_conflict_check(
            kinds=JUDGED_KINDS,
            limit=s.conflict_batch_size,
        )
        if not pending:
            return {"checked": 0, "links": 0, "skipped": "no_pending"}

        for memory in pending:
            # Cost ceiling per tenant. Deliberately *not* marked checked when
            # blocked: the memory stays queued and gets judged once the daily
            # counter rolls over, rather than silently never being judged.
            if not await check_daily_quota(
                bucket="conflict",
                org_id=memory.org_id,
                limit=s.conflict_daily_quota_per_org,
            ):
                quota_blocked += 1
                continue

            candidates = await memories.list_conflict_candidates(
                memory,
                limit=s.conflict_max_candidates,
                min_similarity=s.conflict_similarity_threshold,
            )
            checked.append(memory.id)
            if not candidates:
                continue

            neighbours = [m for m, _ in candidates]
            with span(
                "kortex.conflict.judge",
                memory_id=memory.id,
                org_id=memory.org_id,
                candidates=len(neighbours),
            ) as js:
                verdicts = await judge.judge(
                    _as_candidate(memory),
                    [_as_candidate(m) for m in neighbours],
                )
                js.set_attribute("verdicts", len(verdicts))

            for verdict in verdicts:
                link_type = _RELATION_TO_LINK.get(verdict.relation)
                if link_type is None:
                    continue
                # from = the memory just written, to = the one it conflicts with.
                await links.link(
                    from_memory_id=memory.id,
                    to_memory_id=verdict.memory_id,
                    link_type=link_type,
                    weight=verdict.confidence,
                )
                links_written += 1
                log.info(
                    "conflict_detected",
                    memory_id=memory.id,
                    other_id=verdict.memory_id,
                    relation=verdict.relation,
                    confidence=verdict.confidence,
                )

        await memories.mark_conflict_checked(checked)

    return {
        "checked": len(checked),
        "links": links_written,
        "quota_blocked": quota_blocked,
        "judge": judge.name,
    }


@celery_app.task(name="kortex.conflict.detect_pending", bind=False)
def detect_pending() -> dict[str, int | str]:
    try:
        return asyncio.run(_detect_batch())
    finally:
        try:
            asyncio.run(close_engine())
        except Exception:  # pragma: no cover - cleanup is best-effort
            pass
