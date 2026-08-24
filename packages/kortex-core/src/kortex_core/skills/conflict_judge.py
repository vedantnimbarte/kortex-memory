"""Conflict judge.

Decides whether a newly-written memory conflicts with the existing memories
nearest to it in vector space. Two relations matter:

* ``supersedes`` — the new memory gives a different value for the *same
  attribute* of the *same subject*, and reads as the later state of the world.
* ``contradicts`` — the two cannot both be true, but neither is clearly the
  replacement.

Everything else is ``none``. This bias is deliberate and load-bearing: the
candidates handed to the judge are already the nearest neighbours in the same
scope and of the same kind, so they are *all* topically similar. Similar is not
conflicting. Two memories about the same subsystem, complementary facts, and
statements that can both hold at once ("Alice is CEO" / "Bob is CEO" of
different companies) are all ``none``, and a judge that forgets that produces
a stream of false edges that is worse than no edges at all.

We surface conflicts; we never resolve them. The agent has the conversation
context that decides which side is right — the database does not.

Without a configured LLM the judge degrades to :class:`NullConflictJudge`,
which writes nothing, mirroring the planner-unavailable path in
:mod:`kortex_core.services.agentic_retriever`.
"""

from __future__ import annotations

import datetime as dt
from abc import abstractmethod
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from kortex_core.llm.protocol import LLM, LlmError, LlmMessage
from kortex_core.llm.registry import get_llm
from kortex_core.settings import get_settings
from kortex_core.telemetry.logging import get_logger

log = get_logger("kortex.skills.conflict")

Relation = Literal["none", "contradicts", "supersedes"]


@dataclass(frozen=True, slots=True)
class ConflictCandidate:
    memory_id: int
    public_id: str
    title: str
    body: str
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class ConflictVerdict:
    memory_id: int
    relation: Relation
    confidence: float
    reason: str = ""


@runtime_checkable
class ConflictJudge(Protocol):
    name: str

    @abstractmethod
    async def judge(
        self,
        incoming: ConflictCandidate,
        existing: list[ConflictCandidate],
        /,
    ) -> list[ConflictVerdict]:
        """Return one verdict per conflicting candidate. ``none`` may be omitted."""
        ...


class NullConflictJudge(ConflictJudge):
    """No LLM configured — assert nothing rather than guess."""

    name = "null"

    async def judge(
        self,
        _incoming: ConflictCandidate,
        _existing: list[ConflictCandidate],
        /,
    ) -> list[ConflictVerdict]:
        return []


_SYSTEM = (
    "You compare a NEW memory against EXISTING memories drawn from the same "
    "project. For each existing memory, choose exactly one relation:\n"
    "  * supersedes — the NEW memory gives a different value for the SAME "
    "attribute of the SAME subject, and reads as the later state "
    "(e.g. 'the job queue runs on Postgres' -> 'the job queue runs on Redis').\n"
    "  * contradicts — both cannot be true at once, but neither is clearly the "
    "newer replacement.\n"
    "  * none — everything else.\n"
    "\n"
    "Every candidate you are shown is already topically similar to the new "
    "memory. Similarity is NOT conflict. Complementary facts, different "
    "subjects, different attributes, different environments, and statements "
    "that can both hold at once are all `none`. Two people can both be a CEO; "
    "two services can both use caching; a detail added later does not replace "
    "the fact it elaborates.\n"
    "\n"
    "When in doubt, answer `none`. A missed conflict is recoverable; a false "
    "one corrupts recall for every future session. Set confidence to your "
    "actual certainty, and never invent identifiers."
)

_SCHEMA = {
    "type": "object",
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["index", "relation", "confidence"],
                "properties": {
                    "index": {"type": "integer", "minimum": 0},
                    "relation": {"type": "string", "enum": ["none", "contradicts", "supersedes"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string", "maxLength": 200},
                },
                "additionalProperties": False,
            },
        }
    },
    "additionalProperties": False,
}


def _render(incoming: ConflictCandidate, existing: list[ConflictCandidate]) -> str:
    lines = [
        "NEW memory:",
        f"{incoming.title}\n{incoming.body}".strip(),
        "",
        "EXISTING memories:",
    ]
    for index, candidate in enumerate(existing):
        lines.append(f"[{index}] {candidate.title}\n{candidate.body}".strip())
    return "\n\n".join(lines)


class LLMConflictJudge(ConflictJudge):
    """Judges with the *summarizer* model — this runs on every write, so it has
    to be cheap. The planner-class model is reserved for retrieval."""

    name = "llm"

    def __init__(self, llm: LLM | None = None):
        self._llm = llm

    async def judge(
        self,
        incoming: ConflictCandidate,
        existing: list[ConflictCandidate],
        /,
    ) -> list[ConflictVerdict]:
        if not existing:
            return []
        s = get_settings()
        llm = self._llm
        if llm is None:
            try:
                llm = get_llm(s.llm_provider)
            except (KeyError, LlmError):
                return []

        try:
            resp = await llm.complete(
                messages=[
                    LlmMessage(role="system", content=_SYSTEM),
                    LlmMessage(role="user", content=_render(incoming, existing)),
                ],
                model=s.llm_model_summarizer,
                max_tokens=600,
                temperature=0.0,
                json_schema=_SCHEMA,
            )
        except LlmError as e:
            log.warning("conflict_judge_failed", error=str(e), memory_id=incoming.memory_id)
            return []

        return _parse(resp.structured, existing, s.conflict_min_confidence)


def _parse(
    payload: dict | None,
    existing: list[ConflictCandidate],
    min_confidence: float,
) -> list[ConflictVerdict]:
    """Map raw model output onto candidates, dropping anything unusable.

    Tolerant by construction: a malformed row is skipped rather than raised on,
    because a judge that crashes the write path is worse than one that misses.
    """
    verdicts: list[ConflictVerdict] = []
    for raw in (payload or {}).get("verdicts") or []:
        if not isinstance(raw, dict):
            continue
        relation = raw.get("relation")
        if relation not in ("contradicts", "supersedes"):
            continue  # `none` and anything unrecognised produce no edge
        index = raw.get("index")
        # `bool` is an `int` in Python, so a model that emits `true` here would
        # otherwise silently resolve to candidate 1 and link the wrong memory.
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        if not 0 <= index < len(existing):
            continue
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            continue
        if confidence < min_confidence:
            continue
        verdicts.append(
            ConflictVerdict(
                memory_id=existing[index].memory_id,
                relation=relation,
                confidence=min(1.0, max(0.0, confidence)),
                reason=str(raw.get("reason", ""))[:200],
            )
        )
    return verdicts


_singleton: ConflictJudge | None = None


def get_conflict_judge() -> ConflictJudge:
    """The configured judge, or the null judge when no LLM provider resolves."""
    global _singleton
    if _singleton is None:
        s = get_settings()
        try:
            get_llm(s.llm_provider)
        except (KeyError, LlmError):
            _singleton = NullConflictJudge()
        else:
            _singleton = LLMConflictJudge()
    return _singleton
