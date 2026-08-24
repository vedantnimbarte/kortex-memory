"""Conflict judging and conflict-aware ordering.

The parsing tests matter more than they look: the judge's output decides
whether an edge is written, and a false edge marks a perfectly good memory as
stale for every future recall. Everything ambiguous must fall through to "no
edge".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import pytest
from kortex_core.llm.protocol import LlmError, LlmMessage, LlmResponse
from kortex_core.retrieval.conflicts import ConflictNote, demote_superseded
from kortex_core.settings import get_settings
from kortex_core.skills.conflict_judge import (
    ConflictCandidate,
    LLMConflictJudge,
    NullConflictJudge,
    _parse,
)

NOW = dt.datetime(2026, 8, 25, tzinfo=dt.UTC)


def _candidate(memory_id: int, title: str = "t", body: str = "b") -> ConflictCandidate:
    return ConflictCandidate(
        memory_id=memory_id,
        public_id=f"pid-{memory_id}",
        title=title,
        body=body,
        created_at=NOW,
    )


CANDIDATES = [_candidate(10), _candidate(11), _candidate(12)]


class StubLLM:
    """Records the call and returns a canned structured response."""

    provider = "stub"

    def __init__(self, structured: dict[str, Any] | None = None, error: bool = False):
        self._structured = structured
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        self.calls.append({"messages": messages, "model": model, "temperature": temperature})
        if self._error:
            raise LlmError("stub failure")
        return LlmResponse(text="", structured=self._structured, model=model)


# --- parsing: what becomes an edge, and what must not ------------------------


def test_supersedes_and_contradicts_become_verdicts() -> None:
    payload = {
        "verdicts": [
            {"index": 0, "relation": "supersedes", "confidence": 0.9},
            {"index": 1, "relation": "contradicts", "confidence": 0.75},
        ]
    }
    verdicts = _parse(payload, CANDIDATES, 0.6)
    assert [(v.memory_id, v.relation) for v in verdicts] == [
        (10, "supersedes"),
        (11, "contradicts"),
    ]


def test_none_relation_produces_no_edge() -> None:
    payload = {"verdicts": [{"index": 0, "relation": "none", "confidence": 1.0}]}
    assert _parse(payload, CANDIDATES, 0.6) == []


def test_low_confidence_is_dropped() -> None:
    payload = {"verdicts": [{"index": 0, "relation": "supersedes", "confidence": 0.59}]}
    assert _parse(payload, CANDIDATES, 0.6) == []


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"verdicts": None},
        {"verdicts": ["not a dict"]},
        {"verdicts": [{"relation": "supersedes", "confidence": 0.9}]},  # no index
        {"verdicts": [{"index": 99, "relation": "supersedes", "confidence": 0.9}]},  # out of range
        {"verdicts": [{"index": -1, "relation": "supersedes", "confidence": 0.9}]},
        {"verdicts": [{"index": 0, "relation": "invents_a_relation", "confidence": 0.9}]},
        {"verdicts": [{"index": 0, "relation": "supersedes", "confidence": "high"}]},
        {"verdicts": [{"index": True, "relation": "supersedes", "confidence": 0.9}]},
    ],
)
def test_malformed_output_never_creates_an_edge(payload: Any) -> None:
    assert _parse(payload, CANDIDATES, 0.6) == []


def test_confidence_is_clamped_into_range() -> None:
    payload = {"verdicts": [{"index": 0, "relation": "supersedes", "confidence": 4.2}]}
    assert _parse(payload, CANDIDATES, 0.6)[0].confidence == 1.0


# --- the judges --------------------------------------------------------------


async def test_null_judge_never_asserts_anything() -> None:
    assert await NullConflictJudge().judge(_candidate(1), CANDIDATES) == []


async def test_llm_judge_returns_parsed_verdicts() -> None:
    llm = StubLLM({"verdicts": [{"index": 2, "relation": "supersedes", "confidence": 0.8}]})
    verdicts = await LLMConflictJudge(llm).judge(_candidate(1), CANDIDATES)
    assert [(v.memory_id, v.relation) for v in verdicts] == [(12, "supersedes")]


async def test_llm_judge_is_deterministic_and_uses_the_cheap_model() -> None:
    llm = StubLLM({"verdicts": []})
    await LLMConflictJudge(llm).judge(_candidate(1), CANDIDATES)
    call = llm.calls[0]
    assert call["temperature"] == 0.0
    # The summarizer model, not the planner — this runs on every write.
    settings = get_settings()
    assert call["model"] == settings.llm_model_summarizer
    assert call["model"] != settings.llm_model_planner


async def test_llm_failure_degrades_to_no_edges() -> None:
    """A failing judge must never block or corrupt the write path."""
    assert await LLMConflictJudge(StubLLM(error=True)).judge(_candidate(1), CANDIDATES) == []


async def test_no_candidates_short_circuits_before_calling_the_model() -> None:
    llm = StubLLM({"verdicts": []})
    assert await LLMConflictJudge(llm).judge(_candidate(1), []) == []
    assert llm.calls == []


async def test_prompt_shows_every_candidate_with_its_index() -> None:
    llm = StubLLM({"verdicts": []})
    await LLMConflictJudge(llm).judge(
        _candidate(1, "new", "we moved the queue to Redis"),
        [_candidate(10, "old", "the queue runs on Postgres")],
    )
    user_msg = llm.calls[0]["messages"][1].content
    assert "we moved the queue to Redis" in user_msg
    assert "[0] old" in user_msg


# --- ordering ----------------------------------------------------------------


@dataclass
class _Item:
    mid: int


def _ids(items: list[_Item]) -> list[int]:
    return [i.mid for i in items]


def test_demote_is_a_noop_without_conflicts() -> None:
    items = [_Item(1), _Item(2), _Item(3)]
    assert _ids(demote_superseded(items, set(), key=lambda i: i.mid)) == [1, 2, 3]


def test_superseded_item_sorts_below_its_successor() -> None:
    # 1 is stale, 2 supersedes it, and 1 outranked 2 on score.
    items = [_Item(1), _Item(2), _Item(3)]
    assert _ids(demote_superseded(items, {1}, key=lambda i: i.mid)) == [2, 3, 1]


def test_demotion_is_stable_among_the_demoted() -> None:
    items = [_Item(1), _Item(2), _Item(3), _Item(4)]
    assert _ids(demote_superseded(items, {1, 3}, key=lambda i: i.mid)) == [2, 4, 1, 3]


def test_chained_supersession_keeps_the_newest_first() -> None:
    """C supersedes A supersedes B: only C is current, and it must lead."""
    items = [_Item(1), _Item(2), _Item(3)]  # 1=B, 2=A, 3=C by score order
    assert _ids(demote_superseded(items, {1, 2}, key=lambda i: i.mid)) == [3, 1, 2]


# --- note semantics ----------------------------------------------------------


def test_superseded_by_is_the_stale_side() -> None:
    stale = ConflictNote(public_id="p", title="t", relation="superseded_by", created_at="")
    current = ConflictNote(public_id="p", title="t", relation="supersedes", created_at="")
    contradiction = ConflictNote(public_id="p", title="t", relation="contradicts", created_at="")
    assert stale.is_stale_marker
    assert not current.is_stale_marker
    assert not contradiction.is_stale_marker
