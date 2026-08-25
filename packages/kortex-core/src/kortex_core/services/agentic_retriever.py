"""Agentic recall: plan → execute → rerank → synthesize.

Layout follows plan §G. Each phase has a clear seam so M6+ skills can swap in
without touching the orchestrator:

  * Planner LLM (``KORTEX_LLM_MODEL_PLANNER``) emits a ``QueryPlan``.
  * ``AgentLoop`` dispatches the plan through hybrid retrieval + link graph.
  * ``Reranker`` rescores candidates against the original question.
  * ``TokenBudget`` packs them into a ``ContextBundle`` with citations.
  * (Optional) Summarizer LLM produces a synthesized answer + citations.

If the planner LLM is unavailable or ``KORTEX_AGENTIC_RETRIEVAL=false``, we
fall back to plain hybrid retrieval. The fallback path is the same code path
the M2 ``RetrievalService`` uses, so behaviour stays consistent.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import Sensitivity
from kortex_core.embeddings.protocol import EmbeddingError
from kortex_core.embeddings.registry import get_embedder
from kortex_core.llm.protocol import LLM, LlmError, LlmMessage
from kortex_core.llm.registry import get_llm
from kortex_core.repositories.memory_repo import MemoryRepository, ScopeFilter
from kortex_core.retrieval.agent_loop import AgentLoop, AgentLoopResult
from kortex_core.retrieval.budget import RecallBudget, RecallUsage, should_plan
from kortex_core.retrieval.conflicts import annotate_conflicts, demote_superseded
from kortex_core.retrieval.hybrid import HybridSearchHit
from kortex_core.retrieval.query_plan import (
    QueryPlan,
    SemanticSearch,
    parse_plan,
    query_plan_schema,
)
from kortex_core.retrieval.reranker_pipeline import (
    RerankedHit,
    rerank_and_pack,
)
from kortex_core.security.principal import Principal
from kortex_core.settings import get_settings
from kortex_core.skills.reranker import get_reranker
from kortex_core.telemetry.logging import get_logger
from kortex_core.telemetry.tracing import span

log = get_logger("kortex.retrieval.recall")


@dataclass(frozen=True, slots=True)
class Citation:
    public_id: str
    title: str
    score: float


@dataclass(frozen=True, slots=True)
class ContextBundle:
    """The final output of a recall: ranked memories + optional answer."""

    query: str
    answer: str | None
    citations: list[Citation] = field(default_factory=list)
    candidates: list[RerankedHit] = field(default_factory=list)
    used_tokens: int = 0
    plan_trace: list[str] = field(default_factory=list)
    plan_rationale: str = ""
    hops: int = 0
    stopped_reason: str = ""
    usage: RecallUsage = field(default_factory=RecallUsage)


@dataclass(frozen=True, slots=True)
class RecallRequest:
    query: str
    scopes: list[ScopeFilter] | None = None
    synthesize: bool = False
    max_tokens: int = 0  # 0 → settings default
    per_item_max: int = 800
    latency_budget_ms: int = 0
    """Wall-clock ceiling for the whole call. 0 = unlimited. A budget too small
    for a planner round trip degrades to plain hybrid retrieval."""
    token_budget: int = 0
    """Ceiling on LLM tokens spent planning and synthesising. 0 = unlimited."""


_PLANNER_SYSTEM = (
    "You are the retrieval planner for the Kortex memory layer. Output a "
    "QueryPlan with a short rationale and up to 6 steps that will surface the "
    "memories most relevant to the user's question. Steps:\n"
    " * semantic_search/keyword_search to fan out\n"
    " * link_expand to follow memory_links from prior hits\n"
    " * time_filter to bound when results were stored\n"
    " * stop_and_answer when you have enough.\n"
    "Prefer 2-4 fan-out steps before stopping. Never invent identifiers."
)


_SUMMARIZER_SYSTEM = (
    "You are answering a user question using ONLY the supplied memories. "
    "Cite each memory you use as [m:<public_id>]. If the memories don't "
    "answer the question, say so explicitly. Keep the answer concise."
)


class AgenticRetriever:
    """Top-level recall orchestrator."""

    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        planner: LLM | None = None,
        summarizer: LLM | None = None,
    ):
        self._session = session
        self._principal = principal
        self._planner = planner
        self._summarizer = summarizer
        self._memories = MemoryRepository(session, principal=principal)

    async def recall(self, request: RecallRequest) -> ContextBundle:
        s = get_settings()
        max_tokens = request.max_tokens or s.retrieval_default_max_tokens
        budget = RecallBudget(
            latency_ms=request.latency_budget_ms,
            tokens=request.token_budget,
        )
        usage = RecallUsage()

        with span(
            "kortex.retrieval.recall",
            query_len=len(request.query),
            synthesize=request.synthesize,
            org_id=self._principal.org_id,
            latency_budget_ms=request.latency_budget_ms,
            token_budget=request.token_budget,
        ) as root:
            # Resolve LLMs lazily; missing config falls back to hybrid-only.
            planner = self._planner
            if planner is None and s.agentic_retrieval:
                try:
                    planner = get_llm(s.llm_provider)
                except (KeyError, LlmError):
                    planner = None

            plan_it, skip_reason = should_plan(
                budget,
                planner_available=planner is not None,
                agentic_enabled=s.agentic_retrieval,
                min_budget_ms=s.retrieval_planner_min_budget_ms,
                min_budget_tokens=s.retrieval_planner_min_budget_tokens,
            )
            if not plan_it or planner is None:
                root.set_attribute("path", "fallback")
                root.set_attribute("skip_reason", skip_reason)
                return await self._fallback_hybrid(
                    request, max_tokens, budget, usage, rationale=skip_reason
                )

            root.set_attribute("path", "agentic")
            usage.mode = "agentic"

            try:
                with span("kortex.retrieval.plan") as ps:
                    plan = await self._plan(planner, request, usage)
                    ps.set_attribute("steps", len(plan.steps))
            except LlmError as e:
                log.warning("planner_failed", error=str(e))
                root.set_attribute("path", "fallback_after_plan_error")
                return await self._fallback_hybrid(
                    request,
                    max_tokens,
                    budget,
                    usage,
                    rationale=f"planner failed ({e}); ran plain hybrid retrieval",
                )

            try:
                embedder = get_embedder()
            except (KeyError, EmbeddingError):
                embedder = None

            loop = AgentLoop(
                session=self._session,
                principal=self._principal,
                embedder=embedder,
                scopes=request.scopes,
                budget=budget,
            )
            with span("kortex.retrieval.execute") as es:
                exec_result: AgentLoopResult = await loop.run(plan)
                es.set_attribute("hops", exec_result.hops)
                es.set_attribute("candidates", len(exec_result.candidates))
                es.set_attribute("stopped_reason", exec_result.stopped_reason)

            if not exec_result.candidates:
                seed_step = SemanticSearch(query=request.query, top_k=20)
                fallback_plan = QueryPlan(steps=[seed_step])
                exec_result = await AgentLoop(
                    session=self._session,
                    principal=self._principal,
                    embedder=embedder,
                    scopes=request.scopes,
                    budget=budget,
                ).run(fallback_plan)

            with span("kortex.retrieval.rerank") as rs:
                bundle = await self._rerank_pack(
                    request.query,
                    exec_result.candidates,
                    max_tokens,
                    request.per_item_max,
                )
                rs.set_attribute("kept", len(bundle))

            answer = None
            if request.synthesize:
                # A second model call is the most expensive thing left, so skip
                # it rather than blow a budget the caller set deliberately.
                affords_ms = budget.has_headroom(s.retrieval_planner_min_budget_ms)
                affords_tokens = budget.affords_tokens(
                    usage.total_tokens, s.retrieval_planner_min_budget_tokens
                )
                if not (affords_ms and affords_tokens):
                    usage.budget_exhausted = True
                    log.info(
                        "synthesis_skipped_for_budget",
                        elapsed_ms=round(budget.elapsed_ms()),
                        tokens=usage.total_tokens,
                    )
                else:
                    summarizer = self._summarizer or planner
                    try:
                        with span("kortex.retrieval.synthesize") as syn:
                            answer = await self._synthesize(
                                summarizer, request.query, bundle, usage
                            )
                            syn.set_attribute("answer_chars", len(answer or ""))
                    except LlmError as e:
                        log.warning("summarizer_failed", error=str(e))
                        answer = None

            await self._memories.record_access([r.hit.memory_id for r in bundle])

            usage.plan_steps = len(plan.steps)
            usage.hops = exec_result.hops
            usage.latency_ms = budget.elapsed_ms()
            usage.budget_exhausted = (
                usage.budget_exhausted or exec_result.stopped_reason == "budget_exhausted"
            )
            root.set_attribute("kept", len(bundle))
            root.set_attribute("tokens", usage.total_tokens)
            return ContextBundle(
                query=request.query,
                answer=answer,
                citations=[
                    Citation(
                        public_id=r.hit.public_id,
                        title=r.hit.title,
                        score=r.final_score,
                    )
                    for r in bundle
                ],
                candidates=bundle,
                used_tokens=_used_tokens(bundle, request.per_item_max),
                plan_trace=exec_result.trace,
                plan_rationale=plan.rationale,
                hops=exec_result.hops,
                stopped_reason=exec_result.stopped_reason,
                usage=usage,
            )

    # --- internals ---

    async def _plan(self, planner: LLM, request: RecallRequest, usage: RecallUsage) -> QueryPlan:
        s = get_settings()
        scope_hint = (
            "\nScopes: "
            + json.dumps(
                [{"type": sc.scope_type.value, "id": sc.scope_id} for sc in (request.scopes or [])]
            )
            if request.scopes
            else ""
        )
        user_msg = f"Question: {request.query}{scope_hint}"
        resp = await planner.complete(
            messages=[
                LlmMessage(role="system", content=_PLANNER_SYSTEM),
                LlmMessage(role="user", content=user_msg),
            ],
            model=s.llm_model_planner,
            max_tokens=512,
            temperature=0.2,
            json_schema=query_plan_schema(),
        )
        usage.record(resp, s.llm_prices)
        plan = parse_plan(resp.structured)
        if not plan.steps:
            # Recover gracefully — seed with one semantic step.
            plan = QueryPlan(
                rationale=plan.rationale or "planner returned no steps",
                steps=[SemanticSearch(query=request.query, top_k=20)],
            )
        return plan

    async def _rerank_pack(
        self,
        query: str,
        candidates: Sequence[HybridSearchHit],
        max_tokens: int,
        per_item_max: int,
    ) -> list[RerankedHit]:
        if not candidates:
            return []
        reranker = get_reranker()
        kept, _ = await rerank_and_pack(
            query=query,
            hits=list(candidates),
            reranker=reranker,
            max_tokens=max_tokens,
            per_item_max=per_item_max,
        )
        if not get_settings().conflict_detection:
            return kept
        # Both the agentic and fallback paths funnel through here, so annotating
        # once covers every recall.
        with span("kortex.retrieval.conflicts", candidates=len(kept)) as cs:
            demoted = await annotate_conflicts(
                self._session, self._principal, [r.hit for r in kept]
            )
            cs.set_attribute("demoted", len(demoted))
        return demote_superseded(kept, demoted, key=lambda r: r.hit.memory_id)

    async def _synthesize(
        self, summarizer: LLM, query: str, bundle: list[RerankedHit], usage: RecallUsage
    ) -> str:
        s = get_settings()
        memories_block = "\n\n".join(
            f"[m:{r.hit.public_id}] {r.hit.title}\n{r.hit.body}" for r in bundle
        )
        resp = await summarizer.complete(
            messages=[
                LlmMessage(role="system", content=_SUMMARIZER_SYSTEM),
                LlmMessage(
                    role="user",
                    content=(f"Question: {query}\n\nMemories:\n{memories_block}\n\nAnswer:"),
                ),
            ],
            model=s.llm_model_summarizer,
            max_tokens=600,
            temperature=0.1,
        )
        usage.record(resp, s.llm_prices)
        return resp.text.strip()

    async def _fallback_hybrid(
        self,
        request: RecallRequest,
        max_tokens: int,
        budget: RecallBudget,
        usage: RecallUsage,
        *,
        rationale: str = "",
    ) -> ContextBundle:
        """Plain hybrid retrieval — the one degradation path.

        Reached when no planner is configured, when the planner errored, or
        when the caller's budget cannot fit a model round trip. ``rationale``
        says which, so a caller that expected agentic results can tell a
        deliberate budget decision from a broken planner.
        """
        max_sens = self._principal.max_sensitivity or Sensitivity.INTERNAL
        try:
            embedder = get_embedder()
            vectors = await embedder.embed([request.query])
            query_vector = vectors[0]
            used_vector = True
        except (EmbeddingError, KeyError, RuntimeError):
            query_vector = None
            used_vector = False
        hits = await self._memories.hybrid_search(
            query=request.query,
            query_vector=query_vector,
            scopes=request.scopes,
            max_sensitivity=max_sens,
            limit=50,
        )
        kept = await self._rerank_pack(request.query, hits, max_tokens, request.per_item_max)
        await self._memories.record_access([r.hit.memory_id for r in kept])
        usage.mode = "hybrid"
        usage.latency_ms = budget.elapsed_ms()
        return ContextBundle(
            query=request.query,
            answer=None,
            citations=[
                Citation(public_id=r.hit.public_id, title=r.hit.title, score=r.final_score)
                for r in kept
            ],
            candidates=kept,
            used_tokens=_used_tokens(kept, request.per_item_max),
            plan_trace=[f"fallback:hybrid used_vector={used_vector}"],
            plan_rationale=rationale or "planner unavailable; ran plain hybrid retrieval",
            hops=0,
            stopped_reason="fallback",
            usage=usage,
        )


def _used_tokens(bundle: list[RerankedHit], per_item_max: int) -> int:
    # Cheap proxy reused from token_budget for telemetry display.
    from kortex_core.retrieval.token_budget import estimate_tokens

    total = 0
    for r in bundle:
        text = f"{r.hit.title}\n{r.hit.body}"
        t = estimate_tokens(text)
        total += min(t, per_item_max)
    return total
