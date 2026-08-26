"""Audit retention.

Keeping audit forever is not a virtue. Most regulations that require a trail
also require it to be disposed of on a schedule, and an unbounded append-only
table is a storage bill that grows until someone truncates it in a hurry — the
worst possible way for audit data to disappear.

So retention is deliberate and bounded, and the purge is itself audited. A log
that can be trimmed without saying so is not a log.

Off by default (``audit_retention_days = 0``). Deleting a customer's compliance
evidence because a default said so is not a mistake anyone should be able to
make by not reading the settings.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from kortex_core.audit import AuditAction
from kortex_core.db.engine import close_engine
from kortex_core.db.session import session_scope
from kortex_core.db.types import ActorKind
from kortex_core.repositories.audit_repo import AuditRepository
from kortex_core.security.principal import Principal
from kortex_core.settings import get_settings
from kortex_core.telemetry.logging import get_logger

from kortex_worker.celery_app import celery_app

log = get_logger("kortex.worker.audit")


def _system(org_id: int) -> Principal:
    return Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=org_id,
        is_superuser=True,
    )


async def _purge_org(org_id: int, cutoff: dt.datetime) -> int:
    async with session_scope() as session:
        repo = AuditRepository(session, principal=_system(org_id))
        removed = await repo.purge_before(org_id=org_id, cutoff=cutoff)
        if removed:
            # Written after the delete, in the same transaction, so the count is
            # the real one and the record cannot be lost if the delete rolls
            # back. It becomes the first entry of what remains.
            await repo.append(
                actor_kind=ActorKind.SYSTEM,
                actor_id=None,
                action=str(AuditAction.AUDIT_PURGED),
                target_type="org",
                target_id=org_id,
                metadata={"removed": removed, "cutoff": cutoff.isoformat()},
                org_id=org_id,
            )
        await session.commit()
        return removed


async def _purge_all() -> dict[str, int]:
    days = get_settings().audit_retention_days
    if days <= 0:
        return {"orgs": 0, "removed": 0, "skipped": 1}
    cutoff = dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=days)

    async with session_scope() as session:
        orgs = await AuditRepository(session, principal=_system(0)).orgs_with_entries()

    removed = 0
    for org_id in orgs:
        removed += await _purge_org(org_id, cutoff)
    return {"orgs": len(orgs), "removed": removed, "skipped": 0}


@celery_app.task(name="kortex.audit.purge_expired", bind=False)
def purge_expired() -> dict[str, int]:
    try:
        result = asyncio.run(_purge_all())
    finally:
        asyncio.run(close_engine())
    log.info("audit_retention_run", **result)
    return result
