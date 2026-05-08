"""Token budget packing for context bundles.

We don't have a model-aware tokenizer in M2. This module provides a cheap,
character-based estimate (1 token ≈ 4 chars) used as a placeholder until M5
plugs in tiktoken / anthropic tokenizer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


def estimate_tokens(text: str) -> int:
    """Cheap proxy: ~1 token per 4 characters (rounded up)."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass(slots=True)
class BudgetItem:
    id: int
    text: str
    score: float


@dataclass(slots=True)
class TokenBudget:
    max_tokens: int
    per_item_max: int = 800

    def fit(self, items: Sequence[BudgetItem]) -> tuple[list[BudgetItem], int]:
        """Greedily pack items into the budget, ordered by descending score.

        Returns the kept items and the total estimated tokens consumed. Each item
        is truncated to ``per_item_max`` tokens (proportional char cap) before
        packing.
        """
        ordered = sorted(items, key=lambda i: i.score, reverse=True)
        kept: list[BudgetItem] = []
        used = 0
        for item in ordered:
            text = item.text
            tokens = estimate_tokens(text)
            if tokens > self.per_item_max:
                # Truncate to roughly per_item_max tokens (4 chars/tok).
                text = text[: self.per_item_max * 4]
                tokens = self.per_item_max
            if used + tokens > self.max_tokens:
                continue
            kept.append(BudgetItem(id=item.id, text=text, score=item.score))
            used += tokens
        return kept, used
