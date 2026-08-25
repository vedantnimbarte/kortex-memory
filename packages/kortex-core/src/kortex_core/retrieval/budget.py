"""Latency and token budgets for recall, and the usage a recall reports back.

Agentic recall plans with an LLM before it retrieves, which buys multi-hop
reasoning and costs a model round trip. Whether that trade is worth making
depends entirely on the caller: an interactive agent completing a line of code
wants an answer in 300ms, while a background summarisation job will happily
wait ten seconds for a better one.

So the caller states a budget and the retriever respects it, rather than the
server guessing. A budget that cannot fit the planner degrades to plain hybrid
retrieval — the same path taken when no planner LLM is configured, so there is
one well-tested degradation route rather than two.

Cost is reported only when the operator has supplied prices. Model pricing
changes, varies by contract, and is zero for self-hosted models; a built-in
table would produce confident wrong numbers, which is worse than reporting
tokens and letting the operator multiply.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from kortex_core.llm.protocol import LlmResponse

UNLIMITED = 0
"""Sentinel for "no cap" on both budget dimensions."""


@dataclass(slots=True)
class RecallBudget:
    """What the caller is willing to spend on one recall.

    ``latency_ms`` is wall-clock from the moment the budget is created, so it
    covers embedding, retrieval and reranking too — not just the LLM calls.
    That is the number the caller actually cares about.
    """

    latency_ms: int = UNLIMITED
    tokens: int = UNLIMITED
    _start: float = field(default_factory=time.perf_counter)

    @property
    def has_latency_cap(self) -> bool:
        return self.latency_ms > UNLIMITED

    @property
    def has_token_cap(self) -> bool:
        return self.tokens > UNLIMITED

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000.0

    def remaining_ms(self) -> float | None:
        """Milliseconds left, or None when uncapped. May be negative."""
        if not self.has_latency_cap:
            return None
        return self.latency_ms - self.elapsed_ms()

    def has_headroom(self, need_ms: float) -> bool:
        """True when at least ``need_ms`` of the latency budget remains."""
        remaining = self.remaining_ms()
        return True if remaining is None else remaining >= need_ms

    def tokens_remaining(self, spent: int) -> int | None:
        if not self.has_token_cap:
            return None
        return max(0, self.tokens - spent)

    def affords_tokens(self, spent: int, need: int) -> bool:
        remaining = self.tokens_remaining(spent)
        return True if remaining is None else remaining >= need


@dataclass(slots=True)
class RecallUsage:
    """What one recall actually spent.

    ``cost_usd`` is None rather than 0.0 when the model has no configured
    price. Zero is a measurement; None is the absence of one, and collapsing
    them would let an unpriced deployment report every recall as free.
    """

    mode: str = "hybrid"
    """``agentic`` when the planner ran, ``hybrid`` otherwise."""
    tokens_in: int = 0
    tokens_out: int = 0
    llm_calls: int = 0
    plan_steps: int = 0
    hops: int = 0
    latency_ms: float = 0.0
    cost_usd: float | None = None
    budget_exhausted: bool = False
    """True when a cap cut the work short, so a caller can tell a fast answer
    from a truncated one."""

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    def record(self, response: LlmResponse, prices: dict[str, list[float]] | None = None) -> None:
        """Fold one LLM call into the running total."""
        self.llm_calls += 1
        self.tokens_in += response.tokens_in
        self.tokens_out += response.tokens_out
        cost = price_usd(response.model, response.tokens_in, response.tokens_out, prices)
        if cost is not None:
            self.cost_usd = (self.cost_usd or 0.0) + cost

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "total_tokens": self.total_tokens,
            "llm_calls": self.llm_calls,
            "plan_steps": self.plan_steps,
            "hops": self.hops,
            "latency_ms": round(self.latency_ms, 2),
            "cost_usd": self.cost_usd,
            "budget_exhausted": self.budget_exhausted,
        }


def price_usd(
    model: str,
    tokens_in: int,
    tokens_out: int,
    prices: dict[str, list[float]] | None = None,
) -> float | None:
    """Cost of one call, or None when ``model`` has no configured price.

    ``prices`` maps a model id to ``[input, output]`` USD per million tokens;
    it comes from ``KORTEX_LLM_PRICES`` and is empty by default.
    """
    if prices is None:
        from kortex_core.settings import get_settings

        prices = get_settings().llm_prices
    entry = prices.get(model) if prices else None
    if not entry or len(entry) < 2:
        return None
    per_mtok_in, per_mtok_out = float(entry[0]), float(entry[1])
    return (tokens_in * per_mtok_in + tokens_out * per_mtok_out) / 1_000_000


def should_plan(
    budget: RecallBudget,
    *,
    planner_available: bool,
    agentic_enabled: bool,
    min_budget_ms: int,
    min_budget_tokens: int,
) -> tuple[bool, str]:
    """Decide whether to spend a planner call. Returns (plan, reason).

    The reason is carried into the response's ``plan_rationale`` so a caller
    that got hybrid results when it expected agentic ones can see why, rather
    than concluding the planner is broken.
    """
    if not agentic_enabled:
        return False, "agentic retrieval disabled by configuration"
    if not planner_available:
        return False, "planner unavailable; ran plain hybrid retrieval"
    if budget.has_latency_cap and not budget.has_headroom(min_budget_ms):
        return False, (
            f"latency budget {budget.latency_ms}ms below the {min_budget_ms}ms "
            "a planner round trip needs; ran plain hybrid retrieval"
        )
    if budget.has_token_cap and not budget.affords_tokens(0, min_budget_tokens):
        return False, (
            f"token budget {budget.tokens} below the {min_budget_tokens} "
            "a planner round trip needs; ran plain hybrid retrieval"
        )
    return True, ""
