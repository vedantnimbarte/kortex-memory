"""Retrieval-quality regression gate.

The benchmark harness in ``scripts/eval`` measures the numbers we publish; it
needs a running deployment and, for the real suites, a multi-gigabyte download.
This is the cheap half: a small fixture corpus scored in ordinary CI, so a
change that breaks ranking fails on the pull request that caused it rather than
on the next benchmark run someone remembers to do.

The floors are deliberately loose. They exist to catch *breakage* — an
inverted sort, a dropped scope filter, a fusion bug that returns noise — not to
police small ranking movements, which would make every retrieval tweak a
red build.
"""

from __future__ import annotations

import pytest
from kortex_core.db.types import MemoryKind, ScopeType
from kortex_core.repositories.memory_repo import MemoryRepository
from kortex_core.services.auth_service import AuthService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.signup_service import SignupService

from scripts.eval.datasets import load_synthetic
from scripts.eval.metrics import QueryOutcome, mrr, recall_at_k

pytestmark = pytest.mark.integration

# Small enough to stay fast, large enough that BM25 has to actually rank:
# 8 questions against 8 distractors each.
INSTANCES = 8
HAYSTACK = 8

# BM25-only floors. CI installs no embedder, so this measures keyword
# retrieval; the gold document repeats the question's topic while distractors
# mention it only in passing, so a working ranker clears these comfortably.
MIN_RECALL_AT_1 = 0.5
MIN_RECALL_AT_5 = 0.75
MIN_MRR = 0.6


async def _owner(session, email: str, org: str):  # type: ignore[no-untyped-def]
    result = await SignupService(session).register(
        email=email, password="hunter2pass", org_name=org
    )
    return (await AuthService(session).principal_from_jwt(result.access_token)).principal


async def test_synthetic_corpus_retrieval_does_not_regress(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner(session, "evalgate@acme.io", "Eval Gate")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    memories = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    instances = list(load_synthetic(count=INSTANCES, haystack_size=HAYSTACK))

    # Every instance shares one scope on purpose: cross-instance distractors
    # make this a real ranking problem rather than "find the one document".
    doc_id_by_memory: dict[int, str] = {}
    for instance in instances:
        for doc in instance.documents:
            created = await memories.create(
                CreateMemoryInput(
                    scope_type=ScopeType.WORKSPACE,
                    scope_id=ws.id,
                    title=doc.title,
                    body=doc.body,
                    kind=MemoryKind.EVENT,
                )
            )
            doc_id_by_memory[created.id] = doc.doc_id
    await session.flush()

    outcomes: list[QueryOutcome] = []
    for instance in instances:
        for question in instance.questions:
            # No embedder in CI, so this is the BM25 path — which is also the
            # fallback every deployment lands on when embeddings are unavailable,
            # and therefore worth gating on its own.
            hits = await repo.hybrid_search(
                query=question.question,
                query_vector=None,
                limit=10,
            )
            outcomes.append(
                QueryOutcome(
                    question_id=question.question_id,
                    category=question.category,
                    latency_s=0.0,
                    retrieved_doc_ids=tuple(
                        doc_id_by_memory[h.memory_id]
                        for h in hits
                        if h.memory_id in doc_id_by_memory
                    ),
                    gold_doc_ids=question.gold_doc_ids,
                )
            )

    r1, r5, score = recall_at_k(outcomes, 1), recall_at_k(outcomes, 5), mrr(outcomes)
    assert r1 is not None and r5 is not None and score is not None
    detail = f"recall@1={r1:.3f} recall@5={r5:.3f} mrr={score:.3f} over {len(outcomes)} questions"

    assert r5 >= MIN_RECALL_AT_5, f"top-5 retrieval regressed: {detail}"
    assert r1 >= MIN_RECALL_AT_1, f"top-1 ranking regressed: {detail}"
    assert score >= MIN_MRR, f"ranking quality regressed: {detail}"


async def test_scope_filter_excludes_other_projects(session) -> None:  # type: ignore[no-untyped-def]
    """A scoped search must not reach memories outside the scope.

    Retrieval quality is meaningless if the result set leaks; this is the
    cheapest possible guard on the filter the benchmark relies upon.
    """
    principal = await _owner(session, "evalscope@acme.io", "Eval Scope")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    memories = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    await memories.create(
        CreateMemoryInput(
            scope_type=ScopeType.ORG,
            scope_id=principal.org_id,
            title="org secret",
            body="The deployment target is Kubernetes via the Helm chart.",
            kind=MemoryKind.EVENT,
        )
    )
    inside = await memories.create(
        CreateMemoryInput(
            scope_type=ScopeType.WORKSPACE,
            scope_id=ws.id,
            title="workspace note",
            body="The deployment target is Kubernetes via the Helm chart.",
            kind=MemoryKind.EVENT,
        )
    )
    await session.flush()

    from kortex_core.repositories.memory_repo import ScopeFilter

    hits = await repo.hybrid_search(
        query="deployment target",
        query_vector=None,
        scopes=[ScopeFilter(scope_type=ScopeType.WORKSPACE, scope_id=ws.id)],
        limit=10,
    )
    assert {h.memory_id for h in hits} == {inside.id}
