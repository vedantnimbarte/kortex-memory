"""Decay & tier promotion policy.

Memories fade unless they are pinned or recently accessed. The default policy
implements the formula from plan §F:

    decay = importance
          * exp(-λ_tier * Δt_days)
          * (1 + ln(1 + access_count)) / norm

with ``norm`` recomputed against the cluster's median access count. Pinned
memories are clamped to ``1.0``.

Promotion (short→mid) is automatic when age > 24h AND importance ≥ 0.4 AND
access_count ≥ 1. mid→long is consolidation-driven (see :class:`Consolidator`).
Hard-delete short>7d with decay<0.05; archive mid>180d with decay<0.10.
"""

from __future__ import annotations

import datetime as dt
import math
from abc import abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from kortex_core.db.types import MemoryTier
from kortex_core.settings import get_settings


@dataclass(frozen=True, slots=True)
class DecayInputs:
    """Just the columns the policy needs — keeps it model-agnostic."""

    importance: float
    access_count: int
    last_accessed_at: dt.datetime | None
    created_at: dt.datetime
    tier: MemoryTier
    pinned: bool


@dataclass(frozen=True, slots=True)
class DecayDecision:
    new_decay_score: float
    new_tier: MemoryTier | None  # None means "no change"
    should_hard_delete: bool = False
    should_archive: bool = False


@runtime_checkable
class DecayPolicy(Protocol):
    name: str

    @abstractmethod
    def evaluate(
        self,
        inputs: DecayInputs,
        *,
        now: dt.datetime,
        median_access_count: int = 1,
    ) -> DecayDecision: ...


class ExponentialDecayPolicy(DecayPolicy):
    """Default policy."""

    name = "exponential"

    def evaluate(
        self,
        inputs: DecayInputs,
        *,
        now: dt.datetime,
        median_access_count: int = 1,
    ) -> DecayDecision:
        s = get_settings()
        if inputs.pinned:
            # Pinned bypasses decay entirely.
            return DecayDecision(new_decay_score=1.0, new_tier=None)

        lam = {
            MemoryTier.SHORT: s.decay_lambda_short,
            MemoryTier.MID: s.decay_lambda_mid,
            MemoryTier.LONG: s.decay_lambda_long,
        }[inputs.tier]

        anchor = inputs.last_accessed_at or inputs.created_at
        elapsed_days = max(0.0, (now - anchor).total_seconds() / 86400.0)
        recency = math.exp(-lam * elapsed_days)

        access_norm = math.log1p(max(1, median_access_count))
        access_bias = math.log1p(inputs.access_count) / max(access_norm, 1e-9)

        score = inputs.importance * recency * (1.0 + access_bias)
        score = max(0.0, min(1.0, score))

        new_tier: MemoryTier | None = None

        # short → mid promotion.
        if inputs.tier == MemoryTier.SHORT:
            age_hours = (now - inputs.created_at).total_seconds() / 3600.0
            if (
                age_hours >= s.decay_short_to_mid_age_hours
                and inputs.importance >= 0.4
                and inputs.access_count >= 1
            ):
                new_tier = MemoryTier.MID

        # Hard-delete short memories that are old AND faded.
        should_hard_delete = False
        if inputs.tier == MemoryTier.SHORT:
            age_days = (now - inputs.created_at).total_seconds() / 86400.0
            if age_days >= s.decay_short_delete_age_days and score < s.decay_short_delete_threshold:
                should_hard_delete = True

        # Archive mid memories that are old AND faded.
        should_archive = False
        if inputs.tier == MemoryTier.MID:
            age_days = (now - inputs.created_at).total_seconds() / 86400.0
            if age_days >= s.decay_mid_archive_age_days and score < s.decay_mid_archive_threshold:
                should_archive = True

        return DecayDecision(
            new_decay_score=score,
            new_tier=new_tier,
            should_hard_delete=should_hard_delete,
            should_archive=should_archive,
        )


_singleton: DecayPolicy | None = None


def get_decay_policy() -> DecayPolicy:
    global _singleton
    if _singleton is None:
        _singleton = ExponentialDecayPolicy()
    return _singleton


def reset() -> None:
    global _singleton
    _singleton = None
