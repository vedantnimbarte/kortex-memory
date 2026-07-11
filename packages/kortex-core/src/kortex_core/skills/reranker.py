"""Cross-encoder reranker.

The default skill is :class:`BgeReranker` (``BAAI/bge-reranker-v2-m3``). When
``sentence-transformers`` isn't installed we fall back to a pure-Python
heuristic that biases the fused RRF score by exact-term overlap. The heuristic
is good enough for tests and small dev clusters.
"""

from __future__ import annotations

import asyncio
import threading
from abc import abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RerankCandidate:
    """One candidate going into the reranker."""

    id: int
    text: str
    prior_score: float = 0.0


@runtime_checkable
class Reranker(Protocol):
    """Score candidates against a query. Higher is better."""

    model_id: str

    @abstractmethod
    async def score(self, query: str, candidates: list[RerankCandidate]) -> list[float]: ...


class HeuristicReranker(Reranker):
    """Token-overlap fallback. Stable, dependency-free."""

    model_id = "kortex/heuristic-overlap"

    async def score(self, query: str, candidates: list[RerankCandidate]) -> list[float]:
        q_tokens = {t for t in _tokenize(query) if t}
        out: list[float] = []
        for c in candidates:
            c_tokens = _tokenize(c.text)
            if not c_tokens:
                out.append(c.prior_score)
                continue
            overlap = sum(1 for t in c_tokens if t in q_tokens)
            jaccard = overlap / max(1, len(q_tokens | set(c_tokens)))
            out.append(c.prior_score + jaccard)
        return out


def _tokenize(text: str) -> list[str]:
    return [w for w in text.lower().split() if w.isalnum() or "-" in w or "_" in w]


class BgeReranker(Reranker):
    """``BAAI/bge-reranker-v2-m3`` via sentence-transformers ``CrossEncoder``."""

    model_id = "BAAI/bge-reranker-v2-m3"

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()

    def _load(self) -> object:
        if self._model is not None:
            return self._model  # type: ignore[unreachable]
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import CrossEncoder
                except ImportError as e:  # pragma: no cover - optional dep
                    raise RuntimeError(
                        "sentence-transformers not installed; install kortex-core[embeddings-local]"
                    ) from e
                self._model = CrossEncoder(self.model_id)
        return self._model

    async def score(self, query: str, candidates: list[RerankCandidate]) -> list[float]:
        if not candidates:
            return []
        model = self._load()
        pairs = [(query, c.text) for c in candidates]
        loop = asyncio.get_running_loop()
        scores = await loop.run_in_executor(
            None,
            lambda: list(model.predict(pairs)),  # type: ignore[attr-defined]
        )
        return [float(s) for s in scores]


_singleton: Reranker | None = None


def get_reranker() -> Reranker:
    """Return the configured reranker singleton.

    Defaults to :class:`BgeReranker`; if loading it raises, fall back to
    :class:`HeuristicReranker` so retrieval still works in lean environments.
    """
    global _singleton
    if _singleton is not None:
        return _singleton
    try:
        _singleton = BgeReranker()
        # Force lazy load to surface missing deps now, not mid-recall.
        _singleton._load()
    except Exception:
        _singleton = HeuristicReranker()
    return _singleton


def reset() -> None:
    """Tests only."""
    global _singleton
    _singleton = None
