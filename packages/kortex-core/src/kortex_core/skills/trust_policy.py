"""Where a memory came from, and whether it is trying to give orders.

Sensitivity answers *who may read this*. Trust answers a different question the
schema never asked: *should this have been allowed to influence anything?* A
memory a person wrote and a memory scraped out of a fetched web page are not
equally believable, and until now they were treated identically.

That matters because a memory layer is a prompt-injection **persistence**
layer. Ordinary injection lasts one turn; injection that gets stored is
re-injected into every future session that retrieves it, and nothing in the
transcript explains where the instruction came from.

Two cheap, non-model defences:

* **Provenance trust**, derived from ``source_type``. Nothing to detect — the
  write path already records where content came from, it was simply never used.
* **Injection heuristics**, applied *only to low-trust content*. A person who
  deliberately writes "ignore previous instructions" into their own memory is
  documenting an attack, not launching one, and quarantining that would make
  the feature useless to exactly the security teams most likely to want it.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

from kortex_core.db.types import MemorySource, Sensitivity


class Trust(str, enum.Enum):
    """How much a memory's origin justifies believing it."""

    HIGH = "high"
    """A person wrote it, or an operator entered it deliberately."""
    MEDIUM = "medium"
    """Produced inside a session — agent and user turns, or derived from them."""
    LOW = "low"
    """Content the system ingested from somewhere it does not control."""


_BY_SOURCE: dict[MemorySource, Trust] = {
    MemorySource.MANUAL: Trust.HIGH,
    MemorySource.MESSAGE: Trust.MEDIUM,
    MemorySource.DERIVED: Trust.MEDIUM,
    # The two that carry text the system did not author: a fetched page, an
    # uploaded PDF, the stdout of a tool that called something else.
    MemorySource.TOOL_OUTPUT: Trust.LOW,
    MemorySource.DOCUMENT: Trust.LOW,
}


def trust_for_source(source: MemorySource) -> Trust:
    return _BY_SOURCE.get(source, Trust.LOW)


# --- injection heuristics --------------------------------------------------

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}?"
            r"\b(previous|prior|earlier|above|all)\b[^.\n]{0,20}?"
            r"\b(instruction|prompt|rule|direction|context)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_reassignment",
        re.compile(
            r"\b(you are|act as|pretend to be|from now on you)\b[^.\n]{0,30}"
            r"\b(now|instead|actually|a different)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_probe",
        re.compile(
            r"\b(reveal|print|repeat|show|output|dump)\b[^.\n]{0,30}"
            r"\b(system prompt|initial instructions|your instructions)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltration",
        re.compile(
            r"\b(send|post|upload|forward|exfiltrate)\b[^.\n]{0,40}"
            r"\b(to|at)\b[^.\n]{0,20}(https?://|@)",
            re.IGNORECASE,
        ),
    ),
    (
        "concealment",
        re.compile(
            r"\b(do not|don't|never)\b[^.\n]{0,20}"
            r"\b(tell|inform|mention|reveal|show)\b[^.\n]{0,20}\b(the )?(user|human|operator)\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class InjectionVerdict:
    suspicious: bool
    patterns: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        return ", ".join(self.patterns)


def scan_for_injection(text: str) -> InjectionVerdict:
    """Look for content addressed to the model rather than describing the world.

    Pattern matching, not classification. It will miss a paraphrase and it is
    not meant to be the last line of defence — it is meant to be a line of
    defence that exists, costs nothing per write, and cannot be talked out of
    its opinion the way an LLM judge can.
    """
    if not text:
        return InjectionVerdict(suspicious=False)
    hits = tuple(name for name, pattern in _PATTERNS if pattern.search(text))
    return InjectionVerdict(suspicious=bool(hits), patterns=hits)


def should_quarantine(*, trust: Trust, text: str) -> InjectionVerdict:
    """Whether to withhold this memory from retrieval pending review.

    Only low-trust content is scanned. Someone writing "ignore previous
    instructions" into their own notes is describing an attack; the same string
    arriving from a fetched page is attempting one.
    """
    if trust is not Trust.LOW:
        return InjectionVerdict(suspicious=False)
    return scan_for_injection(text)


# --- retrieval-side filtering ----------------------------------------------

_MIN_TRUST_FOR_SENSITIVE = (Trust.HIGH, Trust.MEDIUM)


def trusts_allowed_for(max_sensitivity: Sensitivity) -> list[str] | None:
    """Trust levels a recall at this ceiling may draw on, or None for all.

    A caller working at ``confidential`` or ``secret`` is doing something where
    being steered by scraped text is the worst outcome, so low-trust memories
    are left out. Ordinary ``internal`` recall is unaffected — filtering
    everything by provenance would quietly discard most of what an ingest
    pipeline stores.
    """
    if max_sensitivity in (Sensitivity.CONFIDENTIAL, Sensitivity.SECRET):
        return [t.value for t in _MIN_TRUST_FOR_SENSITIVE]
    return None
