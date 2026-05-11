"""Importance scorer.

The default ``HybridScorer`` mixes cheap heuristics with an optional LLM judge
when one is available. Heuristics alone are enough to seed M6: longer titles,
decision/preference/procedure kinds, and explicit pinning all bump importance.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from kortex_core.db.types import MemoryKind


@dataclass(frozen=True, slots=True)
class ImportanceInputs:
    kind: MemoryKind
    title: str
    body: str
    pinned: bool = False
    access_count: int = 0


@runtime_checkable
class ImportanceScorer(Protocol):
    name: str

    @abstractmethod
    def score(self, inputs: ImportanceInputs) -> float:
        ...


_KIND_BIAS = {
    MemoryKind.FACT: 0.5,
    MemoryKind.PREFERENCE: 0.55,
    MemoryKind.DECISION: 0.7,
    MemoryKind.PROCEDURE: 0.6,
    MemoryKind.CODE_ARTIFACT: 0.55,
    MemoryKind.EVENT: 0.5,
    MemoryKind.SUMMARY: 0.65,
}


class HybridScorer(ImportanceScorer):
    """Heuristic-only by default; can be subclassed to call an LLM judge."""

    name = "hybrid"

    def score(self, inputs: ImportanceInputs) -> float:
        base = _KIND_BIAS.get(inputs.kind, 0.5)
        if inputs.pinned:
            base = max(base, 0.85)
        # Title presence + length are weak but cheap signals.
        if inputs.title.strip():
            base += 0.05
        if len(inputs.body) > 400:
            base += 0.05
        if inputs.access_count >= 3:
            base += 0.1
        return max(0.0, min(1.0, base))


_singleton: ImportanceScorer | None = None


def get_importance_scorer() -> ImportanceScorer:
    global _singleton
    if _singleton is None:
        _singleton = HybridScorer()
    return _singleton
