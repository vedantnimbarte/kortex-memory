"""Hybrid retrieval primitives.

The actual SQL queries live in :class:`MemoryRepository`. This module owns the
score-fusion math (Reciprocal Rank Fusion) so it can be unit-tested without a
database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotation only — conflicts.py imports the repositories
    from kortex_core.retrieval.conflicts import ConflictNote


@dataclass(slots=True)
class HybridSearchHit:
    """One ranked candidate from hybrid search."""

    memory_id: int
    public_id: str
    title: str
    body: str
    tier: str
    sensitivity: str
    importance: float
    decay_score: float
    pinned: bool
    vector_distance: float | None = None  # cosine distance, lower = closer
    bm25_rank: float | None = None
    score: float = 0.0

    conflicts: list[ConflictNote] = field(default_factory=list)
    """Supersedes/contradicts edges touching this memory. Populated at
    annotation time by :func:`kortex_core.retrieval.conflicts.annotate_conflicts`;
    empty when nothing conflicts or detection is off."""


def rrf_fuse(
    rankings: list[list[int]],
    *,
    k: int = 60,
    pinned: set[int] | None = None,
    pinned_floor: float = 1.0,
) -> dict[int, float]:
    """Reciprocal Rank Fusion.

    Each input list is a ranking of memory ids (best first). Returns a score map
    where score = sum(1/(k+rank)) over all rankings, plus an optional floor for
    pinned memories so they always rise to the top.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, mid in enumerate(ranking, start=1):
            scores[mid] = scores.get(mid, 0.0) + 1.0 / (k + rank)
    if pinned:
        for mid in pinned:
            if mid in scores:
                scores[mid] = max(scores[mid], pinned_floor)
    return scores
