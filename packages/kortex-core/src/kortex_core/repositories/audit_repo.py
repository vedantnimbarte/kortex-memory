"""Audit log repository (append-only, hash-chained).

Every entry carries a digest of its own content plus the previous entry's
digest for the same org. A row that is altered or removed breaks the chain from
that point on, and the break is visible to someone auditing the log even if
they were the one who altered it — provided the head digest was recorded
somewhere outside the database. That last clause is the whole reason
:meth:`head` exists and why the export carries it.

The chain is per org, not global. A shared chain would mean one tenant's write
rate serialising every other tenant's, and would leak the existence of other
orgs' activity into a digest a customer is invited to verify.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text

from kortex_core.db.types import ActorKind
from kortex_core.models.audit import AuditLog
from kortex_core.repositories.base import BaseRepository
from kortex_core.security.request_context import current_origin

GENESIS = "0" * 64
"""What the first entry in an org's chain points at."""


def digest(entry: AuditLog, prev_hash: str) -> str:
    """The canonical digest of one entry.

    Sorted keys and a fixed separator so the same row always hashes the same
    way — a digest that depends on dict ordering verifies on the machine that
    wrote it and nowhere else.

    ``created_at`` is included: without it, an entry could be back-dated to
    change what an auditor believes about *when* something happened while the
    chain still verified.
    """
    payload = json.dumps(
        {
            "org_id": entry.org_id,
            "actor_kind": entry.actor_kind,
            "actor_id": entry.actor_id,
            "action": entry.action,
            "target_type": entry.target_type,
            "target_id": entry.target_id,
            "metadata": entry.metadata_ or {},
            "ip": str(entry.ip) if entry.ip else None,
            "user_agent": entry.user_agent,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ChainStatus:
    """The result of walking an org's chain."""

    org_id: int
    entries: int
    unchained: int
    """Rows written before chaining existed. Not a failure; not a guarantee either."""
    intact: bool
    broken_at: int | None = None
    detail: str = ""
    anchor_prev: str = GENESIS
    """What the earliest surviving entry chains back to.

    ``GENESIS`` means the log is complete from its beginning. Anything else
    means earlier entries are gone -- expected after retention, and the reason
    the purge writes its own entry saying so."""

    @property
    def summary(self) -> str:
        truncated = "" if self.anchor_prev == GENESIS else " (earlier entries purged)"
        if self.intact and not self.unchained:
            return f"{self.entries} entries verified{truncated}"
        if self.intact:
            return f"{self.entries} entries verified{truncated} ({self.unchained} predate chaining)"
        return f"chain broken at entry {self.broken_at}: {self.detail}"


class AuditRepository(BaseRepository[AuditLog]):
    model = AuditLog

    async def append(
        self,
        *,
        actor_kind: ActorKind,
        actor_id: int | None,
        action: str,
        target_type: str | None = None,
        target_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        org_id: int | None = None,
    ) -> AuditLog:
        # Origin comes from the request context unless the caller knows better,
        # so a new audit site records where the call came from without having to
        # remember to ask.
        context_ip, context_agent = current_origin()
        ip = ip or context_ip
        user_agent = user_agent or context_agent
        principal_org = self.principal.org_id if not self.principal.is_superuser else None
        effective_org = org_id if org_id is not None else principal_org
        if effective_org is None:
            raise ValueError("audit append requires an org_id (no principal org)")
        entry = AuditLog(
            org_id=effective_org,
            actor_kind=actor_kind.value,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_=dict(metadata) if metadata else {},
            ip=ip,
            user_agent=user_agent,
        )
        entry.prev_hash = await self._lock_head(effective_org)
        self._session.add(entry)
        # Flushed before hashing so the server default has produced created_at:
        # hashing a null timestamp and storing a real one verifies as broken.
        await self._session.flush()
        entry.entry_hash = digest(entry, entry.prev_hash or GENESIS)
        await self._session.flush()
        return entry

    async def _lock_head(self, org_id: int) -> str:
        """The current head digest for an org, with the row locked.

        ``FOR UPDATE`` serialises concurrent appends within one org. Without it
        two transactions read the same head and write siblings, forking the
        chain into something the verifier reports as tampering when nothing was
        tampered with — a false alarm in an audit trail being considerably
        worse than a slow one.

        ponytail: this makes audit writes per-org serial. Audit volume is a
        rounding error next to memory writes, so that is fine; if it ever is
        not, the fix is a per-org sequence table rather than dropping the chain.
        """
        row = (
            await self._session.execute(
                text(
                    "SELECT entry_hash FROM audit_log WHERE org_id = :org "
                    "ORDER BY id DESC LIMIT 1 FOR UPDATE"
                ),
                {"org": org_id},
            )
        ).first()
        if row is None:
            return GENESIS
        return str(row[0]) if row[0] else GENESIS

    async def head(self, org_id: int) -> str:
        """The org's current head digest, for recording outside this database.

        A chain verified only against itself proves the rows are consistent
        with each other, not that none were removed from the end. Anchoring the
        head somewhere the database operator does not control is what closes
        that.
        """
        row = (
            await self._session.execute(
                text(
                    "SELECT entry_hash FROM audit_log WHERE org_id = :org ORDER BY id DESC LIMIT 1"
                ),
                {"org": org_id},
            )
        ).first()
        return str(row[0]) if row and row[0] else GENESIS

    async def verify(self, org_id: int) -> ChainStatus:
        """Walk an org's chain and report the first break, if any.

        Verification is anchored on the **earliest surviving entry**, not on
        GENESIS. Retention legitimately removes the start of a chain, and a
        verifier that called that tampering would cry wolf on every org with a
        retention policy -- after which nobody reads its output. Deleting from
        the middle or the end still breaks, which is the case it exists for.

        What anchoring cannot detect is a purge of the oldest entries by someone
        who was not entitled to make one. The AUDIT_PURGED entry and an
        externally recorded head are what cover that; ``anchor_prev`` is
        reported so the gap is visible rather than implied.
        """
        stmt = (
            select(AuditLog)
            .where(AuditLog.org_id == org_id)
            .order_by(AuditLog.id)
            .execution_options(yield_per=500)
        )
        expected: str | None = None
        anchor = GENESIS
        entries = unchained = 0
        for entry in (await self._session.execute(stmt)).scalars():
            entries += 1
            if expected is None and entry.entry_hash is not None:
                expected = entry.prev_hash or GENESIS
                anchor = expected
            if entry.entry_hash is None:
                unchained += 1
                continue
            if entry.prev_hash != expected:
                return ChainStatus(
                    org_id=org_id,
                    entries=entries,
                    unchained=unchained,
                    intact=False,
                    broken_at=entry.id,
                    anchor_prev=anchor,
                    detail=(
                        f"expected prev_hash {(expected or GENESIS)[:12]}…, "
                        f"found {(entry.prev_hash or 'null')[:12]}… — "
                        "an earlier entry was altered or removed"
                    ),
                )
            recomputed = digest(entry, entry.prev_hash or GENESIS)
            if recomputed != entry.entry_hash:
                return ChainStatus(
                    org_id=org_id,
                    entries=entries,
                    unchained=unchained,
                    intact=False,
                    broken_at=entry.id,
                    anchor_prev=anchor,
                    detail="this entry's content no longer matches its digest",
                )
            expected = entry.entry_hash
        return ChainStatus(
            org_id=org_id,
            entries=entries,
            unchained=unchained,
            intact=True,
            anchor_prev=anchor,
        )

    async def read(
        self,
        *,
        org_id: int,
        since: dt.datetime | None = None,
        until: dt.datetime | None = None,
        after_id: int = 0,
        limit: int = 1000,
    ) -> list[AuditLog]:
        """A page of entries in chain order.

        Paged by id rather than offset: an offset page over an append-only
        table shifts under a concurrent write, which silently skips entries in
        an export nobody re-reads.
        """
        stmt = select(AuditLog).where(AuditLog.org_id == org_id, AuditLog.id > after_id)
        if since is not None:
            stmt = stmt.where(AuditLog.created_at >= since)
        if until is not None:
            stmt = stmt.where(AuditLog.created_at < until)
        stmt = stmt.order_by(AuditLog.id).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def orgs_with_entries(self) -> list[int]:
        """Distinct orgs that have audit entries, for retention fan-out.

        Enumerated from the audit table rather than the org table: retention
        only has work where there is something to delete, and an org that has
        never been touched does not need a transaction opened for it.
        """
        rows = (await self._session.execute(text("SELECT DISTINCT org_id FROM audit_log"))).all()
        return [int(r[0]) for r in rows]

    async def purge_before(self, *, org_id: int, cutoff: dt.datetime) -> int:
        """Delete entries older than ``cutoff``. Returns how many went.

        Opts the session in to the append-only trigger's retention exemption.
        ``SET LOCAL`` scopes that to this transaction, so a later statement on
        the same connection cannot inherit permission to delete.

        Deleting from the start of a chain does not break it: verification
        walks forward from whatever remains, and the earliest surviving entry
        is reported as unchained rather than as tampering.
        """
        await self._session.execute(text("SET LOCAL kortex.audit_purge = 'on'"))
        deleted = (
            await self._session.execute(
                text(
                    "DELETE FROM audit_log WHERE org_id = :org AND created_at < :cutoff "
                    "RETURNING id"
                ),
                {"org": org_id, "cutoff": cutoff},
            )
        ).all()
        return len(deleted)
