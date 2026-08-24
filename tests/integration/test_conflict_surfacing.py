"""Integration: a superseded memory is surfaced, flagged, and demoted — not hidden.

Covers the whole loop with a stubbed judge (CI has no LLM): write two memories,
run the detector, then recall and check what the agent actually sees.

The false-positive test is the one that matters. Every candidate the judge sees
is already a near neighbour in the same scope and kind, so a judge biased
toward "conflict" would mark half the corpus stale. If that test ever starts
failing, the feature is doing net harm and should be turned off, not tuned.
"""

from __future__ import annotations

import pytest
from kortex_core.db.types import MemoryKind, MemoryLinkType, ScopeType
from kortex_core.repositories.memory_link_repo import MemoryLinkRepository
from kortex_core.repositories.memory_repo import MemoryRepository
from kortex_core.retrieval.conflicts import annotate_conflicts, demote_superseded
from kortex_core.services.auth_service import AuthService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.signup_service import SignupService
from kortex_core.skills.conflict_judge import ConflictCandidate, ConflictVerdict

pytestmark = pytest.mark.integration


class ScriptedJudge:
    """Returns a fixed verdict for whichever candidate matches ``marker``.

    Standing in for the LLM keeps this test about the plumbing — candidate
    selection, edge writing, annotation, ordering — rather than about model
    behaviour, which the unit tests cover.
    """

    name = "scripted"

    def __init__(self, marker: str | None, relation: str = "supersedes"):
        self._marker = marker
        self._relation = relation
        self.seen: list[list[str]] = []

    async def judge(
        self,
        incoming: ConflictCandidate,
        existing: list[ConflictCandidate],
        /,
    ) -> list[ConflictVerdict]:
        self.seen.append([c.body for c in existing])
        if self._marker is None:
            return []
        return [
            ConflictVerdict(memory_id=c.memory_id, relation=self._relation, confidence=0.9)
            for c in existing
            if self._marker in c.body
        ]


async def _owner(session, email: str, org: str):  # type: ignore[no-untyped-def]
    result = await SignupService(session).register(
        email=email, password="hunter2pass", org_name=org
    )
    return (await AuthService(session).principal_from_jwt(result.access_token)).principal


async def _embedded(svc, repo, *, scope_id: int, body: str, vector: list[float]):  # type: ignore[no-untyped-def]
    """Create a memory and give it a deterministic vector.

    Embedding is asynchronous in production; here we set the vector directly so
    the test never depends on a model being downloadable.
    """
    memory = await svc.create(
        CreateMemoryInput(
            scope_type=ScopeType.WORKSPACE,
            scope_id=scope_id,
            body=body,
            kind=MemoryKind.FACT,
        )
    )
    await repo.set_embedding(memory.id, vector, "test-model")
    return memory


def _near(seed: float) -> list[float]:
    """A 1024-dim vector; nearly-parallel vectors sit above the 0.82 threshold."""
    return [1.0] + [seed] * 1023


async def _run_detection(session, principal, judge) -> int:  # type: ignore[no-untyped-def]
    """The body of ``kortex.conflict.detect_pending``, without Celery."""
    memories = MemoryRepository(session, principal=principal)
    links = MemoryLinkRepository(session, principal=principal)
    written = 0
    pending = await memories.list_pending_conflict_check(
        kinds=(MemoryKind.FACT, MemoryKind.PREFERENCE, MemoryKind.DECISION),
        limit=32,
    )
    for memory in pending:
        candidates = await memories.list_conflict_candidates(memory, limit=5, min_similarity=0.82)
        if not candidates:
            continue

        def as_candidate(m):  # type: ignore[no-untyped-def]
            return ConflictCandidate(
                memory_id=m.id,
                public_id=str(m.public_id),
                title=m.title,
                body=m.body,
                created_at=m.created_at,
            )

        for verdict in await judge.judge(
            as_candidate(memory), [as_candidate(m) for m, _ in candidates]
        ):
            await links.link(
                from_memory_id=memory.id,
                to_memory_id=verdict.memory_id,
                link_type=MemoryLinkType(verdict.relation),
                weight=verdict.confidence,
            )
            written += 1
    await memories.mark_conflict_checked([m.id for m in pending])
    return written


async def test_superseded_memory_is_flagged_and_demoted(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner(session, "conflict@acme.io", "Conflict Co")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    old = await _embedded(
        svc,
        repo,
        scope_id=ws.id,
        body="The job queue runs on Postgres.",
        vector=_near(0.10),
    )
    new = await _embedded(
        svc,
        repo,
        scope_id=ws.id,
        body="We moved the job queue to Redis.",
        vector=_near(0.11),
    )

    assert await _run_detection(session, principal, ScriptedJudge("Postgres")) == 1

    links = await MemoryLinkRepository(session, principal=principal).conflict_links(
        [old.id, new.id]
    )
    assert [(link.from_memory_id, link.to_memory_id, link.link_type) for link in links] == [
        (new.id, old.id, MemoryLinkType.SUPERSEDES.value)
    ]

    # Simulate a recall page where the *stale* memory outranked the current one.
    hits = await repo.hybrid_search(query="job queue", query_vector=_near(0.10), limit=10)
    hits = [h for h in hits if h.memory_id in {old.id, new.id}]
    assert {h.memory_id for h in hits} == {old.id, new.id}
    hits.sort(key=lambda h: 0 if h.memory_id == old.id else 1)  # stale first, worst case

    demoted = await annotate_conflicts(session, principal, hits)
    ordered = demote_superseded(hits, demoted, key=lambda h: h.memory_id)

    # Both are returned — nothing is filtered — but Redis now leads.
    assert [h.memory_id for h in ordered] == [new.id, old.id]

    stale, current = ordered[1], ordered[0]
    assert [c.relation for c in stale.conflicts] == ["superseded_by"]
    assert stale.conflicts[0].public_id == str(new.public_id)
    assert stale.conflicts[0].created_at  # timestamps let the agent judge recency
    assert [c.relation for c in current.conflicts] == ["supersedes"]


async def test_similar_but_compatible_memories_produce_no_edges(session) -> None:  # type: ignore[no-untyped-def]
    """The false-positive guard. Near-neighbours are not conflicts."""
    principal = await _owner(session, "nofp@acme.io", "No FP Co")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    a = await _embedded(
        svc,
        repo,
        scope_id=ws.id,
        body="The job queue runs on Redis.",
        vector=_near(0.20),
    )
    b = await _embedded(
        svc,
        repo,
        scope_id=ws.id,
        body="The job queue retries failed tasks five times.",
        vector=_near(0.21),
    )

    judge = ScriptedJudge(None)  # a judge that correctly answers `none`
    assert await _run_detection(session, principal, judge) == 0
    assert judge.seen, "the judge should still have been consulted"

    links = await MemoryLinkRepository(session, principal=principal).conflict_links([a.id, b.id])
    assert links == []

    hits = await repo.hybrid_search(query="job queue", query_vector=_near(0.20), limit=10)
    hits = [h for h in hits if h.memory_id in {a.id, b.id}]
    assert await annotate_conflicts(session, principal, hits) == set()
    assert all(h.conflicts == [] for h in hits)


async def test_detection_marks_memories_checked_exactly_once(session) -> None:  # type: ignore[no-untyped-def]
    """A second pass must not re-judge (and re-bill) the same memories."""
    principal = await _owner(session, "once@acme.io", "Once Co")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    await _embedded(svc, repo, scope_id=ws.id, body="First fact.", vector=_near(0.30))
    await _embedded(svc, repo, scope_id=ws.id, body="Second fact.", vector=_near(0.31))

    judge = ScriptedJudge(None)
    await _run_detection(session, principal, judge)
    first_pass = len(judge.seen)
    assert first_pass > 0

    await _run_detection(session, principal, judge)
    assert len(judge.seen) == first_pass


async def test_unembedded_memories_are_not_judged(session) -> None:  # type: ignore[no-untyped-def]
    """Detection waits for the embedding — there is nothing to compare without one."""
    principal = await _owner(session, "noembed@acme.io", "No Embed Co")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    await svc.create(
        CreateMemoryInput(
            scope_type=ScopeType.WORKSPACE,
            scope_id=ws.id,
            body="Not embedded yet.",
            kind=MemoryKind.FACT,
        )
    )
    repo = MemoryRepository(session, principal=principal)
    pending = await repo.list_pending_conflict_check(kinds=(MemoryKind.FACT,), limit=32)
    assert pending == []
