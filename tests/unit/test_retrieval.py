"""Unit tests for retrieval primitives (no DB)."""

from __future__ import annotations

import pytest
from kortex_core.retrieval.hybrid import rrf_fuse
from kortex_core.retrieval.token_budget import (
    BudgetItem,
    TokenBudget,
    estimate_tokens,
)

pytestmark = pytest.mark.unit


def test_rrf_fuses_two_rankings_consistently() -> None:
    vec = [1, 2, 3, 4]
    bm25 = [3, 4, 5, 6]
    scores = rrf_fuse([vec, bm25], k=60)
    assert set(scores) == {1, 2, 3, 4, 5, 6}
    # Memory 3 appears in both lists at different ranks → highest score.
    assert max(scores, key=lambda i: scores[i]) == 3


def test_rrf_pin_floor() -> None:
    scores = rrf_fuse([[1, 2, 3]], k=60, pinned={3}, pinned_floor=1.0)
    assert scores[3] >= 1.0
    assert scores[1] < scores[3]


def test_rrf_handles_single_ranking() -> None:
    scores = rrf_fuse([[10, 20]], k=60)
    assert scores[10] > scores[20]


def test_token_budget_packs_high_score_first() -> None:
    items = [
        BudgetItem(id=1, text="a" * 400, score=0.1),
        BudgetItem(id=2, text="b" * 400, score=0.9),
        BudgetItem(id=3, text="c" * 400, score=0.5),
    ]
    kept, used = TokenBudget(max_tokens=200, per_item_max=100).fit(items)
    kept_ids = [k.id for k in kept]
    assert kept_ids[0] == 2  # highest score first
    assert used <= 200


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") == 2
    assert estimate_tokens("x" * 400) == 100
