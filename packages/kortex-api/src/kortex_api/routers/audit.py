"""Audit log: export, and prove it was not edited.

Export streams JSONL rather than returning a JSON array. A year of audit for a
busy org does not want to be assembled in memory on either side, and every SIEM
that ingests files ingests newline-delimited JSON.

Field names follow Elastic Common Schema where one exists (``@timestamp``,
``event.action``, ``user.id``, ``source.ip``) because that is what a Splunk or
Elastic pipeline maps without a custom parser, and a custom parser is the step
at which a SIEM integration quietly never gets finished.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from kortex_core.models.audit import AuditLog
from kortex_core.repositories.audit_repo import AuditRepository

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import forbidden
from kortex_api.schemas.audit import AuditVerifyOut

router = APIRouter(prefix="/v1/audit", tags=["audit"])

PAGE = 1000


def _require_admin(principal: PrincipalDep) -> None:
    """Only an org owner or admin may read the audit log.

    It records who did what, from which address — a log that any member can
    read is a map of a colleague's working hours, and in most jurisdictions
    personal data besides.
    """
    from kortex_core.db.types import Role, ScopeType
    from kortex_core.security.principal import ScopeRef

    if principal.is_superuser:
        return
    role = principal.roles.get(ScopeRef(type=ScopeType.ORG, id=principal.org_id))
    if role not in (Role.OWNER, Role.ADMIN):
        raise forbidden("reading the audit log requires an org owner or admin role")


def _ecs(entry: AuditLog) -> dict:
    """One entry, in the shape a SIEM already knows how to read."""
    return {
        "@timestamp": entry.created_at.isoformat() if entry.created_at else None,
        "event": {
            "action": entry.action,
            "id": entry.id,
            "kind": "event",
            "dataset": "kortex.audit",
        },
        "organization": {"id": entry.org_id},
        "user": {"id": entry.actor_id, "type": entry.actor_kind},
        "target": {"type": entry.target_type, "id": entry.target_id},
        "source": {"ip": str(entry.ip) if entry.ip else None},
        "user_agent": {"original": entry.user_agent},
        "kortex": {
            "metadata": entry.metadata_ or {},
            # Carried so a downstream copy can be verified independently of the
            # database it came from — which is the only kind of verification
            # that means anything to someone auditing the database's owner.
            "entry_hash": entry.entry_hash,
            "prev_hash": entry.prev_hash,
        },
    }


@router.get("/export")
async def export_audit(
    principal: PrincipalDep,
    session: SessionDep,
    since: Annotated[dt.datetime | None, Query()] = None,
    until: Annotated[dt.datetime | None, Query()] = None,
) -> StreamingResponse:
    """Stream this org's audit log as JSONL, oldest first.

    Paged by id internally, so a concurrent append during the export cannot
    shift a page boundary and skip an entry — the failure mode of an
    offset-paged export nobody re-reads.
    """
    _require_admin(principal)
    repo = AuditRepository(session, principal=principal)
    org_id = principal.org_id

    async def stream() -> AsyncIterator[bytes]:
        after = 0
        while True:
            page = await repo.read(
                org_id=org_id, since=since, until=until, after_id=after, limit=PAGE
            )
            if not page:
                return
            for entry in page:
                yield (json.dumps(_ecs(entry), default=str) + "\n").encode("utf-8")
            after = page[-1].id

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="kortex-audit.jsonl"'},
    )


@router.get("/verify", response_model=AuditVerifyOut)
async def verify_audit(principal: PrincipalDep, session: SessionDep) -> AuditVerifyOut:
    """Walk the hash chain and report whether it is intact.

    ``head`` is the value to record somewhere outside this database. Verifying
    a chain against itself proves the entries are consistent with each other;
    it cannot prove none were removed from the end, and only an externally held
    head closes that.
    """
    _require_admin(principal)
    repo = AuditRepository(session, principal=principal)
    status = await repo.verify(principal.org_id)
    return AuditVerifyOut(
        org_id=status.org_id,
        entries=status.entries,
        unchained=status.unchained,
        intact=status.intact,
        broken_at=status.broken_at,
        detail=status.detail,
        summary=status.summary,
        head=await repo.head(principal.org_id),
    )
