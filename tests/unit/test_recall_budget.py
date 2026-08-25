"""Recall budgets: when to skip the planner, and what a recall reports it spent.

The decision this pins is a trade the caller makes, not one the server should
make for them. An interactive agent asking for 300ms wants hybrid results
inside the budget more than it wants multi-hop reasoning outside it — and the
failure mode worth preventing is a "budget" that gets politely ignored.

The other half is honest accounting. `cost_usd` must stay `None` for a model
nobody priced, because reporting 0.0 would tell an operator their LLM bill is
zero.
"""

from __future__ import annotations

import time

import pytest
from kortex_core.llm.protocol import LlmResponse
from kortex_core.retrieval.budget import (
    UNLIMITED,
    RecallBudget,
    RecallUsage,
    price_usd,
    should_plan,
)

PRICES = {"cheap-model": [1.0, 2.0], "free-model": [0.0, 0.0]}
MIN_MS = 1500
MIN_TOKENS = 1024


def _plan_decision(budget: RecallBudget, **over: object) -> tuple[bool, str]:
    kw: dict = {
        "planner_available": True,
        "agentic_enabled": True,
        "min_budget_ms": MIN_MS,
        "min_budget_tokens": MIN_TOKENS,
    }
    return should_plan(budget, **(kw | over))  # type: ignore[arg-type]


# --- budget arithmetic ---


def test_zero_means_unlimited_on_both_axes() -> None:
    budget = RecallBudget()
    assert not budget.has_latency_cap
    assert not budget.has_token_cap
    assert budget.remaining_ms() is None
    assert budget.tokens_remaining(10_000) is None
    assert budget.has_headroom(1_000_000)
    assert budget.affords_tokens(10_000, 10_000)


def test_remaining_latency_decreases_as_time_passes() -> None:
    budget = RecallBudget(latency_ms=5000)
    first = budget.remaining_ms()
    time.sleep(0.02)
    second = budget.remaining_ms()
    assert first is not None and second is not None
    assert second < first
    assert second <= 5000


def test_headroom_is_false_once_the_need_exceeds_what_is_left() -> None:
    budget = RecallBudget(latency_ms=50)
    assert budget.has_headroom(10)
    assert not budget.has_headroom(10_000)


def test_token_budget_accounts_for_what_is_already_spent() -> None:
    budget = RecallBudget(tokens=1000)
    assert budget.tokens_remaining(400) == 600
    assert budget.affords_tokens(400, 600)
    assert not budget.affords_tokens(400, 601)


def test_token_remaining_never_goes_negative() -> None:
    assert RecallBudget(tokens=100).tokens_remaining(500) == 0


# --- the planner decision ---


def test_generous_budget_plans() -> None:
    plan, reason = _plan_decision(RecallBudget(latency_ms=30_000, tokens=100_000))
    assert plan is True
    assert reason == ""


def test_unlimited_budget_plans() -> None:
    assert _plan_decision(RecallBudget())[0] is True


def test_tight_latency_budget_skips_the_planner() -> None:
    """The acceptance case: 100ms cannot fit a model round trip."""
    plan, reason = _plan_decision(RecallBudget(latency_ms=100))
    assert plan is False
    assert "latency budget 100ms" in reason
    assert "hybrid" in reason


def test_tight_token_budget_skips_the_planner() -> None:
    plan, reason = _plan_decision(RecallBudget(tokens=10))
    assert plan is False
    assert "token budget 10" in reason


def test_budget_just_above_the_floor_still_plans() -> None:
    assert _plan_decision(RecallBudget(latency_ms=MIN_MS + 500, tokens=MIN_TOKENS + 1))[0] is True


def test_missing_planner_skips_with_its_own_reason() -> None:
    plan, reason = _plan_decision(RecallBudget(), planner_available=False)
    assert plan is False
    assert "planner unavailable" in reason


def test_disabled_agentic_retrieval_skips_with_its_own_reason() -> None:
    plan, reason = _plan_decision(RecallBudget(), agentic_enabled=False)
    assert plan is False
    assert "disabled by configuration" in reason


def test_every_skip_explains_itself() -> None:
    """A caller that got hybrid results needs to tell a deliberate budget
    decision from a broken planner."""
    for kwargs in (
        {"planner_available": False},
        {"agentic_enabled": False},
    ):
        assert _plan_decision(RecallBudget(), **kwargs)[1]
    assert _plan_decision(RecallBudget(latency_ms=1))[1]
    assert _plan_decision(RecallBudget(tokens=1))[1]


# --- pricing ---


def test_price_is_none_for_an_unpriced_model() -> None:
    """None means unpriced. 0.0 would claim the call was free."""
    assert price_usd("unknown-model", 1000, 1000, PRICES) is None


def test_price_is_none_for_a_malformed_entry() -> None:
    assert price_usd("broken", 10, 10, {"broken": [1.0]}) is None


def test_price_is_computed_per_million_tokens() -> None:
    # 1M in at $1 + 1M out at $2
    assert price_usd("cheap-model", 1_000_000, 1_000_000, PRICES) == pytest.approx(3.0)
    assert price_usd("cheap-model", 1000, 500, PRICES) == pytest.approx(
        (1000 * 1.0 + 500 * 2.0) / 1_000_000
    )


def test_a_genuinely_free_model_reports_zero_not_none() -> None:
    """Self-hosted models cost nothing, and that is a measurement."""
    assert price_usd("free-model", 5000, 5000, PRICES) == 0.0


# --- usage accounting ---


def _response(model: str = "cheap-model", tin: int = 100, tout: int = 50) -> LlmResponse:
    return LlmResponse(text="", structured=None, model=model, tokens_in=tin, tokens_out=tout)


def test_usage_accumulates_across_calls() -> None:
    usage = RecallUsage()
    usage.record(_response(tin=100, tout=50), PRICES)
    usage.record(_response(tin=200, tout=25), PRICES)
    assert usage.llm_calls == 2
    assert usage.tokens_in == 300
    assert usage.tokens_out == 75
    assert usage.total_tokens == 375


def test_usage_sums_cost_across_calls() -> None:
    usage = RecallUsage()
    usage.record(_response(tin=1_000_000, tout=0), PRICES)
    usage.record(_response(tin=1_000_000, tout=0), PRICES)
    assert usage.cost_usd == pytest.approx(2.0)


def test_unpriced_calls_leave_cost_none_while_still_counting_tokens() -> None:
    usage = RecallUsage()
    usage.record(_response(model="unknown", tin=1000, tout=1000), PRICES)
    assert usage.cost_usd is None
    assert usage.total_tokens == 2000


def test_a_hybrid_recall_reports_no_llm_spend() -> None:
    usage = RecallUsage()
    assert usage.mode == "hybrid"
    assert usage.total_tokens == 0
    assert usage.llm_calls == 0
    assert usage.cost_usd is None


def test_usage_serialises_every_field_the_api_exposes() -> None:
    usage = RecallUsage(mode="agentic", plan_steps=3, hops=2, latency_ms=1234.567)
    usage.record(_response(), PRICES)
    payload = usage.as_dict()
    assert set(payload) == {
        "mode",
        "tokens_in",
        "tokens_out",
        "total_tokens",
        "llm_calls",
        "plan_steps",
        "hops",
        "latency_ms",
        "cost_usd",
        "budget_exhausted",
    }
    assert payload["latency_ms"] == 1234.57
    assert payload["mode"] == "agentic"


def test_budget_exhausted_defaults_off() -> None:
    """It must mean "a cap cut this short", not "a budget was set"."""
    assert RecallUsage().budget_exhausted is False


def test_unlimited_sentinel_is_zero() -> None:
    assert UNLIMITED == 0
    assert RecallBudget(latency_ms=UNLIMITED).remaining_ms() is None
