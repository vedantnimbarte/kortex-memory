"""Memory service: CRUD + linking + access bookkeeping."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import (
    MemoryKind,
    MemoryLinkType,
    MemorySource,
    MemoryTier,
    ReviewMode,
    ReviewStatus,
    ScopeType,
    Sensitivity,
)
from kortex_core.dedup import content_hash
from kortex_core.embeddings.registry import get_embedder
from kortex_core.models.memory import Memory, MemoryLink
from kortex_core.repositories.audit_repo import AuditRepository
from kortex_core.repositories.memory_link_repo import MemoryLinkRepository
from kortex_core.repositories.memory_repo import (
    MemoryAnalytics,
    MemoryRepository,
    ScopeFilter,
)
from kortex_core.repositories.org_repo import OrgRepository
from kortex_core.repositories.project_repo import ProjectRepository
from kortex_core.security.plan_limits import QuotaExceededError, max_memories
from kortex_core.security.principal import Principal, ScopeRef
from kortex_core.services.access_control import AccessControl, ResourceRef
from kortex_core.services.access_control import AccessDeniedError as _AccessDenied
from kortex_core.settings import get_settings
from kortex_core.skills.pii_detector import get_pii_detector, summarise
from kortex_core.skills.pii_detector import redact as redact_text
from kortex_core.skills.review_policy import decide_review
from kortex_core.skills.trust_policy import (
    InjectionVerdict,
    should_quarantine,
    trust_for_source,
)
from kortex_core.telemetry.logging import get_logger

log = get_logger("kortex.memory.governance")


@dataclass(frozen=True, slots=True)
class CreateMemoryInput:
    scope_type: ScopeType
    scope_id: int
    body: str
    title: str = ""
    kind: MemoryKind = MemoryKind.FACT
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    source_type: MemorySource = MemorySource.MANUAL
    source_ref: dict | None = None
    importance: float = 0.5
    pinned: bool = False
    metadata: dict | None = None
    expires_at: dt.datetime | None = None
    confidence: float | None = None
    """The writer's own certainty, 0-1. None means it did not say, which is
    treated as certain — an agent that never reports confidence should not have
    every write queued."""


@dataclass(frozen=True, slots=True)
class MemoryWrite:
    """The outcome of a write: the stored memory, and whether it was new.

    ``deduped`` lets a caller tell "I created this" from "this already
    existed", which an agent needs in order to avoid reporting that it saved
    something it merely re-confirmed.
    """

    memory: Memory
    deduped: bool
    pii_flags: dict[str, int] = field(default_factory=dict)
    """Counts by kind of what the detector found. Empty when nothing did."""
    redacted: bool = False
    pending_review: bool = False
    """True when the memory was withheld from retrieval pending review —
    whether for suspicion or for low confidence."""
    review_reason: str = ""


class MemoryService:
    """Stateless service. Builds repos lazily; commit is the caller's job."""

    def __init__(self, session: AsyncSession, principal: Principal):
        self._session = session
        self._principal = principal
        self._repo = MemoryRepository(session, principal=principal)
        self._links = MemoryLinkRepository(session, principal=principal)
        self._ac = AccessControl()
        # Plan-quota state, cached across a batch (e.g. git-log ingest) so we
        # don't re-query the org/count per created memory.
        self._org_plan: str | None = None
        self._mem_count: int | None = None
        self._review_modes: dict[int, ReviewMode] | None = None

    def _require_scope(self, name: str) -> None:
        """Enforce API-key scopes (no-op for users, whose key_scopes is empty)."""
        if not self._principal.has_key_scope(name):
            raise _AccessDenied(f"api key missing required scope {name!r}")

    async def _enforce_memory_quota(self) -> None:
        """Reject creation past the org's plan cap. Unlimited plans skip the
        count query entirely; capped plans count once then track locally."""
        if self._org_plan is None:
            org = await OrgRepository(self._session, principal=self._principal).get_by_id(
                self._principal.org_id
            )
            self._org_plan = org.plan if org else "free"
        cap = max_memories(self._org_plan)
        if cap < 0:
            return  # unlimited
        if self._mem_count is None:
            self._mem_count = await self._repo.count_for_org(self._principal.org_id)
        if self._mem_count >= cap:
            raise QuotaExceededError(
                f"memory limit reached for the {self._org_plan} plan "
                f"({cap:,} memories). Upgrade your plan to store more."
            )
        self._mem_count += 1

    async def _review_mode(self, payload: CreateMemoryInput) -> ReviewMode:
        """Gating is a per-project setting; anything not in a project is ungated.

        Cached per service instance so a batch ingest resolves it once rather
        than per memory.
        """
        if payload.scope_type is not ScopeType.PROJECT:
            return ReviewMode.OFF
        if self._review_modes is None:
            self._review_modes = {}
        cached = self._review_modes.get(payload.scope_id)
        if cached is None:
            project = await ProjectRepository(self._session, principal=self._principal).get_by_id(
                payload.scope_id
            )
            cached = ReviewMode(project.review_mode) if project else ReviewMode.OFF
            self._review_modes[payload.scope_id] = cached
        return cached

    async def review(
        self,
        public_id: uuid.UUID,
        *,
        approve: bool,
    ) -> Memory | None:
        """Approve or reject a held memory, and say so in the audit log.

        Every decision is recorded with who made it. A review trail that cannot
        answer "who approved this" is not a trail, and this is the surface an
        enterprise buyer asks about first.
        """
        self._require_scope("write:memory")
        memory = await self._repo.get_by_public_id(public_id)
        if memory is None:
            return None
        self._require_write(memory)
        if memory.review_status != ReviewStatus.PENDING.value:
            return memory
        status = ReviewStatus.APPROVED if approve else ReviewStatus.REJECTED
        reviewer = self._principal.actor_id if self._principal.actor_kind.value == "user" else None
        await self._repo.set_review_status(memory, status=status, reviewer_id=reviewer)
        await AuditRepository(self._session, principal=self._principal).append(
            actor_kind=self._principal.actor_kind,
            actor_id=self._principal.actor_id,
            action=f"memory.review.{status.value}",
            target_type="memory",
            target_id=memory.id,
            metadata={"reason": memory.review_reason or "", "scope_id": memory.scope_id},
        )
        return memory

    async def pending_review(self, *, limit: int = 50, offset: int = 0) -> list[Memory]:
        self._require_scope("read:memory")
        return await self._repo.list_pending_review(limit=limit, offset=offset)

    async def pending_review_count(self) -> int:
        self._require_scope("read:memory")
        return await self._repo.count_pending_review()

    async def similar_for_review(self, memory: Memory, *, limit: int = 3) -> list[Memory]:
        """What the reviewer needs to tell "new fact" from "fourth restatement"."""
        return await self._repo.find_similar_for_review(memory, limit=limit)

    def _require_write(self, memory: Memory) -> None:
        scope = ScopeRef(type=ScopeType(memory.scope_type), id=memory.scope_id)
        if not self._ac.can_write(
            self._principal,
            ResourceRef(scope=scope, sensitivity=Sensitivity(memory.sensitivity)),
        ):
            raise _AccessDenied(f"cannot modify {memory.sensitivity} memory in {scope}")

    async def create(
        self,
        payload: CreateMemoryInput,
        *,
        embed_inline: bool = False,
        force: bool = False,
    ) -> Memory:
        """Store a memory, folding away a verbatim repeat. See :meth:`write`."""
        result = await self.write(payload, embed_inline=embed_inline, force=force)
        return result.memory

    async def write(
        self,
        payload: CreateMemoryInput,
        *,
        embed_inline: bool = False,
        force: bool = False,
    ) -> MemoryWrite:
        """Store a memory and report whether it was new.

        When an identical memory already exists in the same scope, the existing
        one is returned with its access count bumped instead of a second copy
        being stored — otherwise both compete for space in every future recall
        and the caller pays context tokens to read the same sentence twice.
        ``force=True`` stores the copy anyway.

        Every write is also scanned for personal and secret data and assigned a
        trust level from its ``source_type``. It is held out of retrieval
        pending review when it is low-trust and reads as instructions to a
        model, or when the project gates writes and this one did not clear the
        bar. What the PII scan *does* is set by ``pii_policy``; the default
        only records what it found.
        """
        self._require_scope("write:memory")
        scope_ref = ScopeRef(type=payload.scope_type, id=payload.scope_id)
        if not self._ac.can_write(
            self._principal,
            ResourceRef(scope=scope_ref, sensitivity=payload.sensitivity),
        ):
            raise _AccessDenied(f"cannot write {payload.sensitivity.value} memory in {scope_ref}")
        settings = get_settings()

        # Governance before dedup: the fingerprint has to be taken from the
        # text that will actually be stored, or a redacted write and its
        # unredacted twin fingerprint differently and both get kept.
        title, body = payload.title, payload.body
        trust = trust_for_source(payload.source_type)
        findings: dict[str, int] = {}
        redacted = False
        sensitivity = payload.sensitivity

        if settings.pii_detection:
            matches = get_pii_detector().scan(f"{title}\n{body}")
            if matches:
                findings = summarise(matches)
                if settings.pii_policy == "redact":
                    title = redact_text(title, get_pii_detector().scan(title))
                    body = redact_text(body, get_pii_detector().scan(body))
                    redacted = True
                elif settings.pii_policy == "escalate" and sensitivity in (
                    Sensitivity.PUBLIC,
                    Sensitivity.INTERNAL,
                ):
                    sensitivity = Sensitivity.CONFIDENTIAL
                log.info(
                    "pii_detected",
                    org_id=self._principal.org_id,
                    policy=settings.pii_policy,
                    kinds=sorted(findings),
                )

        verdict = (
            should_quarantine(trust=trust, text=f"{title}\n{body}")
            if settings.injection_quarantine
            else InjectionVerdict(suspicious=False)
        )
        review = decide_review(
            mode=await self._review_mode(payload),
            confidence=payload.confidence,
            threshold=settings.review_confidence_threshold,
            suspicious_reason=verdict.reason if verdict.suspicious else "",
        )
        if review.held:
            log.warning(
                "memory_held_for_review",
                org_id=self._principal.org_id,
                source=payload.source_type.value,
                reason=review.reason,
            )

        digest: str | None = None
        if settings.dedup_on_write:
            digest = content_hash(title, body)
            if not force:
                existing = await self._repo.find_by_content_hash(
                    scope_type=payload.scope_type,
                    scope_id=payload.scope_id,
                    content_hash=digest,
                )
                if existing is not None:
                    # Checked before the quota deliberately: folding a repeat
                    # into an existing memory stores nothing new, so it must not
                    # be able to push an org over its plan cap.
                    await self._repo.record_duplicate(existing, metadata=payload.metadata)
                    return MemoryWrite(memory=existing, deduped=True)
            # A forced copy still records its fingerprint, so a later unforced
            # write folds into the original rather than adding a third row.

        await self._enforce_memory_quota()

        embedding: list[float] | None = None
        embedding_model: str | None = None
        if embed_inline:
            embedder = get_embedder()
            text = (payload.title + "\n" + payload.body).strip() or payload.body
            vectors = await embedder.embed([text])
            embedding = vectors[0]
            embedding_model = embedder.model_id

        created = await self._repo.create(
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            body=body,
            title=title,
            kind=payload.kind,
            sensitivity=sensitivity,
            source_type=payload.source_type,
            source_ref=payload.source_ref,
            importance=payload.importance,
            pinned=payload.pinned,
            metadata=payload.metadata,
            expires_at=payload.expires_at,
            embedding=embedding,
            embedding_model=embedding_model,
            created_by=(
                self._principal.actor_id if self._principal.actor_kind.value == "user" else None
            ),
            content_hash=digest,
            trust=trust.value,
            pii_flags=findings,
            review_status=review.status.value,
            review_reason=review.reason or None,
            confidence=payload.confidence,
        )
        return MemoryWrite(
            memory=created,
            deduped=False,
            pii_flags=findings,
            redacted=redacted,
            pending_review=review.held,
            review_reason=review.reason,
        )

    async def get(self, public_id: uuid.UUID) -> Memory | None:
        self._require_scope("read:memory")
        memory = await self._repo.get_by_public_id(public_id)
        if memory is None:
            return None
        scope = ScopeRef(type=ScopeType(memory.scope_type), id=memory.scope_id)
        if not self._ac.can_read(
            self._principal,
            ResourceRef(scope=scope, sensitivity=Sensitivity(memory.sensitivity)),
        ):
            return None
        return memory

    async def list_(
        self,
        *,
        scope: ScopeFilter | None = None,
        tier: MemoryTier | None = None,
        kind: MemoryKind | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        self._require_scope("read:memory")
        # Cap results to the sensitivity the caller may read; without this a
        # VIEWER could read SECRET bodies via the list endpoint that GET-by-id
        # denies. Superusers are unbounded.
        max_sensitivity = None if self._principal.is_superuser else self._principal.max_sensitivity
        return await self._repo.list_(
            scope=scope,
            tier=tier,
            kind=kind,
            limit=limit,
            offset=offset,
            max_sensitivity=max_sensitivity,
        )

    async def analytics(
        self,
        *,
        now: dt.datetime,
        scope: ScopeFilter | None = None,
        days: int = 14,
        top_n: int = 5,
    ) -> MemoryAnalytics:
        self._require_scope("read:memory")
        # Same sensitivity cap as list_: aggregates only count what the caller
        # may read, so a VIEWER's dashboard never leaks SECRET totals.
        max_sensitivity = None if self._principal.is_superuser else self._principal.max_sensitivity
        return await self._repo.analytics(
            now=now, scope=scope, max_sensitivity=max_sensitivity, days=days, top_n=top_n
        )

    async def update(
        self,
        public_id: uuid.UUID,
        *,
        title: str | None = None,
        body: str | None = None,
        kind: MemoryKind | None = None,
        sensitivity: Sensitivity | None = None,
        importance: float | None = None,
        metadata: dict | None = None,
    ) -> Memory | None:
        self._require_scope("write:memory")
        memory = await self._repo.get_by_public_id(public_id)
        if memory is None:
            return None
        self._require_write(memory)
        # Re-classifying to a higher tier requires write access at that tier too.
        if sensitivity is not None and not self._ac.can_write(
            self._principal,
            ResourceRef(
                scope=ScopeRef(type=ScopeType(memory.scope_type), id=memory.scope_id),
                sensitivity=sensitivity,
            ),
        ):
            raise _AccessDenied(f"cannot set sensitivity {sensitivity.value}")
        return await self._repo.update_fields(
            memory,
            title=title,
            body=body,
            kind=kind,
            sensitivity=sensitivity,
            importance=importance,
            metadata=metadata,
        )

    async def delete(self, public_id: uuid.UUID) -> bool:
        self._require_scope("write:memory")
        memory = await self._repo.get_by_public_id(public_id)
        if memory is None:
            return False
        self._require_write(memory)
        await self._repo.soft_delete(memory)
        return True

    async def set_pinned(self, public_id: uuid.UUID, pinned: bool) -> Memory | None:
        self._require_scope("write:memory")
        memory = await self._repo.get_by_public_id(public_id)
        if memory is None:
            return None
        self._require_write(memory)
        await self._repo.set_pinned(memory, pinned)
        return memory

    async def bulk_apply(self, action: str, public_ids: Sequence[uuid.UUID]) -> int:
        """Apply one action to many memories, reusing the single-item paths so
        each still enforces scope + RBAC. Returns the number actually changed
        (missing/unreadable ids are skipped); an access denial aborts the batch."""
        changed = 0
        for pid in public_ids:
            if action == "pin":
                ok = await self.set_pinned(pid, True) is not None
            elif action == "unpin":
                ok = await self.set_pinned(pid, False) is not None
            elif action == "delete":
                ok = await self.delete(pid)
            else:
                raise ValueError(f"unknown bulk action {action!r}")
            changed += int(ok)
        return changed

    async def link(
        self,
        *,
        from_public_id: uuid.UUID,
        to_public_id: uuid.UUID,
        link_type: MemoryLinkType = MemoryLinkType.RELATED,
        weight: float = 1.0,
    ) -> MemoryLink | None:
        a = await self._repo.get_by_public_id(from_public_id)
        b = await self._repo.get_by_public_id(to_public_id)
        if a is None or b is None:
            return None
        return await self._links.link(
            from_memory_id=a.id,
            to_memory_id=b.id,
            link_type=link_type,
            weight=weight,
        )

    async def list_links(self, public_id: uuid.UUID) -> list[tuple[Memory, str]]:
        """Linked memories for a memory (either direction), each with its link
        type. Returns [] if the memory is missing or unreadable."""
        self._require_scope("read:memory")
        mem = await self._repo.get_by_public_id(public_id)
        if mem is None:
            return []
        out: list[tuple[Memory, str]] = []
        for link in await self._links.neighbors(mem.id):
            other_id = link.to_memory_id if link.from_memory_id == mem.id else link.from_memory_id
            other = await self._repo.get_by_id(other_id)
            if other is not None:
                out.append((other, link.link_type))
        return out

    async def unlink(
        self,
        *,
        from_public_id: uuid.UUID,
        to_public_id: uuid.UUID,
        link_type: MemoryLinkType,
    ) -> bool:
        a = await self._repo.get_by_public_id(from_public_id)
        b = await self._repo.get_by_public_id(to_public_id)
        if a is None or b is None:
            return False
        return await self._links.unlink(
            from_memory_id=a.id,
            to_memory_id=b.id,
            link_type=link_type,
        )

    async def record_access(self, ids: Sequence[int]) -> None:
        await self._repo.record_access(ids)
