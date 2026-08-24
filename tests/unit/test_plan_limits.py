"""Unit tests for per-plan resource caps."""

from __future__ import annotations

from kortex_core.security.plan_limits import (
    PLAN_LIMITS,
    limits_for,
    max_memories,
    max_workspaces,
)


def test_known_plans() -> None:
    assert max_memories("free") == 25_000
    assert max_memories("pro") == 100_000
    assert max_memories("team") == 1_000_000
    assert max_workspaces("free") == 1
    assert max_workspaces("pro") == -1  # unlimited
    assert max_workspaces("team") == -1


def test_unknown_plan_falls_back_to_free() -> None:
    # Fail closed: an unrecognized plan string gets the most restrictive caps.
    assert limits_for("enterprise-legacy") == PLAN_LIMITS["free"]
    assert max_memories("") == max_memories("free")


def test_unlimited_is_negative_one() -> None:
    # The service treats cap < 0 as "skip the count entirely".
    assert max_workspaces("pro") < 0
    assert max_memories("team") > 0
