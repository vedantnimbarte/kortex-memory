"""Per-plan resource caps (billing tiers → hard limits).

Distinct from :mod:`kortex_core.security.quota` (daily cost ceilings) and the
per-minute rate limiter: these are persistent count caps on stored resources —
what a paid plan buys more of. ``-1`` means unlimited.
"""

from __future__ import annotations

from dataclasses import dataclass


class QuotaExceededError(Exception):
    """Raised when an action would exceed the org's plan limit. Maps to HTTP 402."""


@dataclass(frozen=True, slots=True)
class PlanLimits:
    max_memories: int
    max_workspaces: int


PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(max_memories=25_000, max_workspaces=1),
    "pro": PlanLimits(max_memories=100_000, max_workspaces=-1),
    "team": PlanLimits(max_memories=1_000_000, max_workspaces=-1),
}

# Unknown/legacy plan strings fall back to the free tier (fail closed, not open).
_DEFAULT = PLAN_LIMITS["free"]


def limits_for(plan: str) -> PlanLimits:
    return PLAN_LIMITS.get(plan, _DEFAULT)


def max_memories(plan: str) -> int:
    return limits_for(plan).max_memories


def max_workspaces(plan: str) -> int:
    return limits_for(plan).max_workspaces
