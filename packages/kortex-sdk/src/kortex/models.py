"""Typed views over the JSON the API returns.

Frozen dataclasses rather than pydantic models: the server has already
validated everything by the time it reaches you, so a second validation pass
buys nothing and would make ``pip install kortex`` drag in a dependency this
package otherwise does not need.

Every ``_from`` **ignores keys it does not know**. That is the forward-compat
contract: a server that grows a field does not break clients that have not been
upgraded. The raw payload stays on ``.raw`` so a new field is reachable before
this package catches up.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


def _dt(value: Any) -> dt.datetime | None:
    """Parse an API timestamp, tolerating the trailing Z that Python rejects."""
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class ConflictNote:
    """Another memory that disagrees with the one carrying this note.

    ``relation`` is stated from the annotated memory's point of view:
    ``superseded_by`` means *this* memory is the stale side.
    """

    public_id: str
    title: str
    relation: str
    created_at: str = ""

    @classmethod
    def _from(cls, d: dict[str, Any]) -> ConflictNote:
        return cls(
            public_id=str(d.get("public_id", "")),
            title=str(d.get("title", "")),
            relation=str(d.get("relation", "")),
            created_at=str(d.get("created_at", "")),
        )


@dataclass(frozen=True, slots=True)
class Memory:
    """A stored memory."""

    id: str
    """The ``public_id``. Everything that takes a memory takes this."""
    title: str
    body: str
    kind: str
    scope_type: str
    scope_id: int
    sensitivity: str
    tier: str
    importance: float
    pinned: bool
    metadata: dict[str, Any]
    trust: str
    review_status: str
    """Only ``approved`` is retrievable; ``pending`` is waiting on a human."""
    review_reason: str | None
    embedding_state: str
    """``pending``/``failed`` mean this is not in vector search yet. Keyword
    search still finds it."""
    deduped: bool
    """True when a write folded into an existing identical memory instead of
    creating a new one. Only ever set on a create response."""
    created_at: dt.datetime | None
    updated_at: dt.datetime | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def pending_review(self) -> bool:
        return self.review_status == "pending"

    @classmethod
    def _from(cls, d: dict[str, Any]) -> Memory:
        return cls(
            id=str(d.get("public_id", "")),
            title=str(d.get("title", "")),
            body=str(d.get("body", "")),
            kind=str(d.get("kind", "")),
            scope_type=str(d.get("scope_type", "")),
            scope_id=int(d.get("scope_id", 0)),
            sensitivity=str(d.get("sensitivity", "")),
            tier=str(d.get("tier", "")),
            importance=float(d.get("importance", 0.0)),
            pinned=bool(d.get("pinned", False)),
            metadata=dict(d.get("metadata") or {}),
            trust=str(d.get("trust", "medium")),
            review_status=str(d.get("review_status", "approved")),
            review_reason=d.get("review_reason"),
            embedding_state=str(d.get("embedding_state", "pending")),
            deduped=bool(d.get("deduped", False)),
            created_at=_dt(d.get("created_at")),
            updated_at=_dt(d.get("updated_at")),
            raw=d,
        )


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One ranked result."""

    id: str
    title: str
    body: str
    score: float
    tier: str
    sensitivity: str
    importance: float
    decay_score: float
    pinned: bool
    conflicts: list[ConflictNote]
    """Non-empty means something in the corpus contradicts this hit. Worth
    showing a user before they act on it."""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, d: dict[str, Any]) -> SearchHit:
        return cls(
            id=str(d.get("public_id", "")),
            title=str(d.get("title", "")),
            body=str(d.get("body", "")),
            score=float(d.get("score", d.get("final_score", 0.0))),
            tier=str(d.get("tier", "")),
            sensitivity=str(d.get("sensitivity", "")),
            importance=float(d.get("importance", 0.0)),
            decay_score=float(d.get("decay_score", 0.0)),
            pinned=bool(d.get("pinned", False)),
            conflicts=[ConflictNote._from(c) for c in d.get("conflicts") or []],
            raw=d,
        )


@dataclass(frozen=True, slots=True)
class SearchResult:
    hits: list[SearchHit]
    used_vector: bool
    """False means the embedder was unavailable and this was keyword-only. The
    results are still real, just ranked without semantics -- worth logging."""

    def __iter__(self) -> Iterator[SearchHit]:
        return iter(self.hits)

    def __len__(self) -> int:
        return len(self.hits)

    @classmethod
    def _from(cls, d: dict[str, Any]) -> SearchResult:
        return cls(
            hits=[SearchHit._from(h) for h in d.get("hits") or []],
            used_vector=bool(d.get("used_vector", False)),
        )


@dataclass(frozen=True, slots=True)
class Citation:
    id: str
    title: str
    score: float

    @classmethod
    def _from(cls, d: dict[str, Any]) -> Citation:
        return cls(
            id=str(d.get("public_id", "")),
            title=str(d.get("title", "")),
            score=float(d.get("score", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class Usage:
    """What a recall cost."""

    mode: str
    tokens_in: int
    tokens_out: int
    total_tokens: int
    llm_calls: int
    hops: int
    latency_ms: float
    cost_usd: float | None
    """``None`` means the model has no configured price, not that it was free."""
    budget_exhausted: bool

    @classmethod
    def _from(cls, d: dict[str, Any]) -> Usage:
        return cls(
            mode=str(d.get("mode", "")),
            tokens_in=int(d.get("tokens_in", 0)),
            tokens_out=int(d.get("tokens_out", 0)),
            total_tokens=int(d.get("total_tokens", 0)),
            llm_calls=int(d.get("llm_calls", 0)),
            hops=int(d.get("hops", 0)),
            latency_ms=float(d.get("latency_ms", 0.0)),
            cost_usd=None if d.get("cost_usd") is None else float(d["cost_usd"]),
            budget_exhausted=bool(d.get("budget_exhausted", False)),
        )


@dataclass(frozen=True, slots=True)
class Recall:
    """A context bundle: what to put in the prompt, and what it cost to pick."""

    query: str
    answer: str | None
    """Only set when ``synthesize=True`` was asked for."""
    citations: list[Citation]
    candidates: list[SearchHit]
    used_tokens: int
    plan_trace: list[str]
    plan_rationale: str
    hops: int
    stopped_reason: str
    usage: Usage
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def as_prompt(self, separator: str = "\n\n") -> str:
        """The candidates as one block of text, ready to drop into a prompt.

        The single most common thing anyone does with a recall, so it ships
        here instead of being rewritten in every integration.
        """
        return separator.join(
            f"{c.title}\n{c.body}".strip() if c.title else c.body for c in self.candidates
        )

    @classmethod
    def _from(cls, d: dict[str, Any]) -> Recall:
        return cls(
            query=str(d.get("query", "")),
            answer=d.get("answer"),
            citations=[Citation._from(c) for c in d.get("citations") or []],
            candidates=[SearchHit._from(c) for c in d.get("candidates") or []],
            used_tokens=int(d.get("used_tokens", 0)),
            plan_trace=[str(s) for s in d.get("plan_trace") or []],
            plan_rationale=str(d.get("plan_rationale", "")),
            hops=int(d.get("hops", 0)),
            stopped_reason=str(d.get("stopped_reason", "")),
            usage=Usage._from(d.get("usage") or {}),
            raw=d,
        )


@dataclass(frozen=True, slots=True)
class Tokens:
    """A logged-in session."""

    access_token: str
    refresh_token: str
    expires_in: int

    @classmethod
    def _from(cls, d: dict[str, Any]) -> Tokens:
        return cls(
            access_token=str(d.get("access_token", "")),
            refresh_token=str(d.get("refresh_token", "")),
            expires_in=int(d.get("expires_in", 0)),
        )
