"""ExponentialDecayPolicy unit tests."""

from __future__ import annotations

import datetime as dt

from kortex_core.db.types import MemoryTier
from kortex_core.skills.decay_policy import (
    DecayInputs,
    ExponentialDecayPolicy,
)


def _inputs(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "importance": 0.5,
        "access_count": 0,
        "last_accessed_at": None,
        "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        "tier": MemoryTier.SHORT,
        "pinned": False,
    }
    base.update(overrides)
    return DecayInputs(**base)


def test_pinned_clamps_to_one() -> None:
    p = ExponentialDecayPolicy()
    decision = p.evaluate(
        _inputs(pinned=True),
        now=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
        median_access_count=1,
    )
    assert decision.new_decay_score == 1.0
    assert decision.new_tier is None
    assert not decision.should_hard_delete


def test_short_to_mid_promotion() -> None:
    p = ExponentialDecayPolicy()
    decision = p.evaluate(
        _inputs(importance=0.7, access_count=3),
        now=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
        median_access_count=1,
    )
    assert decision.new_tier == MemoryTier.MID


def test_no_promotion_for_low_importance() -> None:
    p = ExponentialDecayPolicy()
    decision = p.evaluate(
        _inputs(importance=0.2, access_count=3),
        now=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
        median_access_count=1,
    )
    assert decision.new_tier is None


def test_short_hard_delete_after_long_inactivity() -> None:
    p = ExponentialDecayPolicy()
    decision = p.evaluate(
        _inputs(importance=0.1, access_count=0),
        now=dt.datetime(2026, 1, 30, tzinfo=dt.UTC),
        median_access_count=1,
    )
    assert decision.should_hard_delete is True


def test_decay_decreases_over_time() -> None:
    p = ExponentialDecayPolicy()
    early = p.evaluate(
        _inputs(importance=0.7),
        now=dt.datetime(2026, 1, 1, 12, tzinfo=dt.UTC),
        median_access_count=1,
    )
    later = p.evaluate(
        _inputs(importance=0.7),
        now=dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
        median_access_count=1,
    )
    assert later.new_decay_score < early.new_decay_score
