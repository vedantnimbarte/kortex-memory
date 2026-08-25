"""Budget-aware recall, end to end against a real database.

The unit tests pin the decision; these pin that the decision is actually
honoured by the orchestrator — that a tight budget really does leave the
planner uncalled, and that a recall reports what it spent.

A stub planner is injected so the assertion can be on its call count. "The
planner was skipped" is only meaningful if something would otherwise have
called it.
"""

from __future__ import annotations

from typing import Any

import pytest
from kortex_core.db.types import MemoryKind, ScopeType
from kortex_core.llm.protocol import LlmMessage, LlmResponse
from kortex_core.services.agentic_retriever import AgenticRetriever, RecallRequest
from kortex_core.services.auth_service import AuthService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.signup_service import SignupService

pytestmark = pytest.mark.integration


class CountingLLM:
    """A planner that records every call and returns a one-step plan."""

    provider = "stub"

    def __init__(self, model: str = "stub-model") -> None:
        self.calls: list[dict[str, Any]] = []
        self._model = model

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        self.calls.append({"model": model, "schema": json_schema})
        if json_schema is not None:
            return LlmResponse(
                text="",
                structured={
                    "rationale": "stub plan",
                    "steps": [{"type": "semantic_search", "query": "queue", "top_k": 10}],
                },
                model=self._model,
                tokens_in=120,
                tokens_out=40,
            )
        return LlmResponse(text="a stub answer", model=self._model, tokens_in=200, tokens_out=60)


async def _owner(session, email: str, org: str):  # type: ignore[no-untyped-def]
    result = await SignupService(session).register(
        email=email, password="hunter2pass", org_name=org
    )
    return (await AuthService(session).principal_from_jwt(result.access_token)).principal


async def _seed(session, principal) -> None:  # type: ignore[no-untyped-def]
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    for body in (
        "The job queue runs on Celery with Redis as the broker.",
        "The job queue retries failed tasks five times before parking them.",
    ):
        await svc.create(
            CreateMemoryInput(
                scope_type=ScopeType.WORKSPACE,
                scope_id=ws.id,
                title="job queue",
                body=body,
                kind=MemoryKind.EVENT,
            )
        )
    await session.flush()


async def test_tight_latency_budget_never_calls_the_planner(session) -> None:  # type: ignore[no-untyped-def]
    """The acceptance case for #12: 100ms buys hybrid results, not a round trip."""
    principal = await _owner(session, "budget1@acme.io", "Budget Co")
    await _seed(session, principal)
    planner = CountingLLM()

    bundle = await AgenticRetriever(session, principal, planner=planner).recall(
        RecallRequest(query="job queue", latency_budget_ms=100)
    )

    assert planner.calls == [], "a 100ms budget must not buy a planner round trip"
    assert bundle.candidates, "skipping the planner must still return results"
    assert bundle.usage.mode == "hybrid"
    assert bundle.usage.total_tokens == 0
    assert bundle.usage.cost_usd is None
    assert bundle.usage.llm_calls == 0
    # The caller has to be able to tell this from a broken planner.
    assert "latency budget" in bundle.plan_rationale


async def test_tight_token_budget_never_calls_the_planner(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner(session, "budget2@acme.io", "Budget Co 2")
    await _seed(session, principal)
    planner = CountingLLM()

    bundle = await AgenticRetriever(session, principal, planner=planner).recall(
        RecallRequest(query="job queue", token_budget=10)
    )

    assert planner.calls == []
    assert bundle.usage.mode == "hybrid"
    assert "token budget" in bundle.plan_rationale


async def test_generous_budget_plans_and_reports_its_spend(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner(session, "budget3@acme.io", "Budget Co 3")
    await _seed(session, principal)
    planner = CountingLLM()

    bundle = await AgenticRetriever(session, principal, planner=planner).recall(
        RecallRequest(query="job queue", latency_budget_ms=60_000, token_budget=100_000)
    )

    assert len(planner.calls) == 1, "a generous budget should buy exactly one planner call"
    assert bundle.usage.mode == "agentic"
    assert bundle.usage.llm_calls == 1
    assert bundle.usage.tokens_in == 120
    assert bundle.usage.tokens_out == 40
    assert bundle.usage.total_tokens == 160
    assert bundle.usage.plan_steps >= 1
    assert bundle.usage.latency_ms > 0


async def test_unlimited_budget_still_plans(session) -> None:  # type: ignore[no-untyped-def]
    """The default path must be unchanged by the budget work."""
    principal = await _owner(session, "budget4@acme.io", "Budget Co 4")
    await _seed(session, principal)
    planner = CountingLLM()

    bundle = await AgenticRetriever(session, principal, planner=planner).recall(
        RecallRequest(query="job queue")
    )
    assert len(planner.calls) == 1
    assert bundle.usage.mode == "agentic"


async def test_synthesis_is_skipped_when_the_budget_cannot_fund_it(session) -> None:  # type: ignore[no-untyped-def]
    """Planning may fit while a second call does not; the answer is dropped,
    the retrieved context is not."""
    principal = await _owner(session, "budget5@acme.io", "Budget Co 5")
    await _seed(session, principal)
    planner = CountingLLM()

    # Enough tokens for the planner (needs 1024 free) but not for another call
    # once the planner has spent 160.
    bundle = await AgenticRetriever(session, principal, planner=planner).recall(
        RecallRequest(query="job queue", synthesize=True, token_budget=1100)
    )

    assert len(planner.calls) == 1, "planner should have run; only synthesis is unaffordable"
    assert bundle.answer is None
    assert bundle.usage.budget_exhausted is True
    assert bundle.candidates, "a skipped answer must not cost the caller its context"


async def test_cost_is_reported_when_the_model_is_priced(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from kortex_core.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_prices", {"stub-model": [1.0, 2.0]}, raising=False)

    principal = await _owner(session, "budget6@acme.io", "Budget Co 6")
    await _seed(session, principal)

    bundle = await AgenticRetriever(session, principal, planner=CountingLLM()).recall(
        RecallRequest(query="job queue", latency_budget_ms=60_000)
    )
    # 120 in @ $1/Mtok + 40 out @ $2/Mtok
    assert bundle.usage.cost_usd == pytest.approx((120 * 1.0 + 40 * 2.0) / 1_000_000)
