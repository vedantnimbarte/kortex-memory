"""Read another vendor's memory export and turn it into Kortex writes.

Deliberately **tolerant** parsers rather than strict schemas. These formats are
not versioned contracts anyone publishes — they are whatever a given SDK
version's ``get_all()`` or agent-serialisation happens to emit, and they move.
A parser pinned to one exact shape breaks on first contact with a real file and
tells the user nothing useful.

So each parser accepts a small set of container shapes (a bare list, or a list
under any of several known keys) and reads fields by alias. What it cannot
place, it keeps: every unmapped key survives in ``metadata`` under the source's
name, so an import is never lossy even where it is imperfect.

**These are built from the vendors' documented API shapes and exercised against
synthetic fixtures, not against real exports from paid accounts.** If one
misreads your file, ``--dry-run`` shows exactly what it made of it before
anything is written, and the parser is thirty lines to correct.

Nothing here writes. Parsers return records; the caller sends them through the
ordinary create path, so dedup, PII scanning and review gating apply to
imported memories exactly as they do to any other write.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

MAX_TITLE = 200
"""Titles are derived from body text; long ones are noise in a result list."""


@dataclass(frozen=True, slots=True)
class SourceMemory:
    """One memory as it arrived, before Kortex has an opinion about it."""

    body: str
    title: str = ""
    kind: str = "fact"
    source_id: str = ""
    """The vendor's own identifier, kept so a re-import is traceable to its origin."""
    metadata: dict[str, Any] = field(default_factory=dict)


class UnreadableExportError(Exception):
    """The file could not be read as the named format."""


# --- shape helpers ----------------------------------------------------------


def _records(doc: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Find the list of records in a document that may or may not wrap them.

    Exports arrive as a bare list, or under ``results``, or under ``memories``,
    depending on the vendor and the SDK version that wrote them. Rather than
    guess one and fail on the others, look for any of them.
    """
    if isinstance(doc, list):
        return [r for r in doc if isinstance(r, dict)]
    if not isinstance(doc, dict):
        raise UnreadableExportError("expected a JSON object or array at the top level")
    for key in keys:
        value = doc.get(key)
        if isinstance(value, list):
            return [r for r in value if isinstance(r, dict)]
        if isinstance(value, dict):  # keyed by id rather than listed
            return [r for r in value.values() if isinstance(r, dict)]
    raise UnreadableExportError(
        f"found none of {', '.join(keys)} in the file, and it is not a bare array. "
        "Check --from matches the tool that produced it."
    )


def _first(record: dict[str, Any], *names: str) -> str:
    """The first of ``names`` present and non-empty, as a string."""
    for name in names:
        value = record.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _title_from(body: str) -> str:
    """A title for a record that has none.

    The first line, or the first sentence of a single-line body. Better than an
    empty title, which makes every row in a memory list look identical.
    """
    head = body.strip().split("\n", 1)[0].strip()
    if len(head) > MAX_TITLE:
        head = head[: MAX_TITLE - 1].rsplit(" ", 1)[0] + "…"
    return head


def _leftovers(record: dict[str, Any], consumed: Iterable[str]) -> dict[str, Any]:
    """Everything the parser did not map, so an import is never lossy.

    A field this parser has no place for is still a field the user had a reason
    to store. Dropping it silently is how migrations lose data that nobody
    notices for six months.
    """
    skip = set(consumed)
    return {k: v for k, v in record.items() if k not in skip and v not in (None, "", [], {})}


def _stamp(source: str, record: dict[str, Any], consumed: Iterable[str]) -> dict[str, Any]:
    extra = _leftovers(record, consumed)
    return {"imported_from": source, **({source: extra} if extra else {})}


# --- mem0 -------------------------------------------------------------------


def parse_mem0(doc: Any) -> list[SourceMemory]:
    """mem0 — flat memories, each a sentence of extracted fact.

    ``get_all()`` returns either a bare list or ``{"results": [...]}`` depending
    on client version; both are accepted. The text lives in ``memory``, with
    ``text``/``content`` seen in older payloads.

    mem0's ``categories`` become metadata rather than Kortex kinds: its category
    set is open and user-extensible, so mapping it onto our seven fixed kinds
    would be guesswork that silently mislabels. Everything lands as ``fact``,
    which is what a mem0 memory actually is.
    """
    out: list[SourceMemory] = []
    for record in _records(doc, ("results", "memories", "data")):
        body = _first(record, "memory", "text", "content", "data")
        if not body:
            continue
        out.append(
            SourceMemory(
                body=body,
                title=_title_from(body),
                kind="fact",
                source_id=_first(record, "id", "memory_id", "hash"),
                metadata=_stamp(
                    "mem0", record, ("memory", "text", "content", "data", "id", "memory_id")
                ),
            )
        )
    return out


# --- zep --------------------------------------------------------------------


def parse_zep(doc: Any) -> list[SourceMemory]:
    """Zep — a knowledge graph of facts, plus the messages they came from.

    Facts are what transfers. Zep's value is the extracted edge ("Alice prefers
    email"), not the transcript it was extracted from, and importing raw
    messages would flood a Kortex scope with conversational noise that the
    write path would then have to decay away.

    Invalidated facts (``invalid_at`` set) are skipped: Zep has already decided
    they are superseded, and re-importing them would resurrect contradictions
    the source system resolved.
    """
    out: list[SourceMemory] = []
    for record in _records(doc, ("facts", "edges", "relevant_facts", "results", "memories")):
        if record.get("invalid_at") or record.get("expired_at"):
            continue
        body = _first(record, "fact", "content", "summary", "name")
        if not body:
            continue
        out.append(
            SourceMemory(
                body=body,
                title=_first(record, "name") or _title_from(body),
                kind="fact",
                source_id=_first(record, "uuid", "uuid_", "id", "edge_uuid"),
                metadata=_stamp(
                    "zep", record, ("fact", "content", "summary", "uuid", "uuid_", "id")
                ),
            )
        )
    return out


# --- letta ------------------------------------------------------------------

_LETTA_BLOCK_KINDS = {"persona": "preference", "human": "preference"}
"""Letta's two conventional core blocks describe who the agent and the user
are — that is a preference in Kortex terms, not a fact about the world."""


def parse_letta(doc: Any) -> list[SourceMemory]:
    """Letta / MemGPT — core memory blocks and archival passages.

    Two different things share one file and they do not import the same way.

    *Core memory blocks* are a small, always-in-context, labelled set (``persona``,
    ``human``, and whatever else the agent defines). They are pinned by
    construction in Letta, so they arrive marked pinned here — a block that was
    always in Letta's context should not decay out of Kortex's.

    *Archival passages* are the long tail Letta searches on demand. Those map
    onto ordinary memories.
    """
    out: list[SourceMemory] = []

    for block in _letta_blocks(doc):
        body = _first(block, "value", "text", "content")
        if not body:
            continue
        label = _first(block, "label", "name") or "block"
        out.append(
            SourceMemory(
                body=body,
                title=f"letta:{label}",
                kind=_LETTA_BLOCK_KINDS.get(label, "fact"),
                source_id=_first(block, "id", "block_id"),
                metadata={
                    **_stamp("letta", block, ("value", "text", "content", "id", "block_id")),
                    "letta_block": label,
                    "pinned_hint": True,
                },
            )
        )

    for passage in _letta_passages(doc):
        body = _first(passage, "text", "content", "value")
        if not body:
            continue
        out.append(
            SourceMemory(
                body=body,
                title=_title_from(body),
                kind="fact",
                source_id=_first(passage, "id", "passage_id"),
                metadata=_stamp("letta", passage, ("text", "content", "value", "id")),
            )
        )

    if not out:
        raise UnreadableExportError(
            "no core memory blocks or archival passages found. A Letta agent file "
            "keeps them under 'blocks'/'core_memory' and 'archival_passages'."
        )
    return out


def _letta_blocks(doc: Any) -> list[dict[str, Any]]:
    """Core memory blocks, wherever this agent file version put them."""
    if isinstance(doc, list):
        return []
    if not isinstance(doc, dict):
        return []
    for key in ("blocks", "core_memory", "memory_blocks"):
        value = doc.get(key)
        if isinstance(value, list):
            return [b for b in value if isinstance(b, dict)]
        if isinstance(value, dict):
            # Older shape: {"persona": "...", "human": "..."} rather than a list.
            return [
                {"label": label, "value": text}
                for label, text in value.items()
                if isinstance(text, str)
            ]
    agents = doc.get("agents")
    if isinstance(agents, list):
        return [b for agent in agents if isinstance(agent, dict) for b in _letta_blocks(agent)]
    return []


def _letta_passages(doc: Any) -> list[dict[str, Any]]:
    if isinstance(doc, list):
        return [p for p in doc if isinstance(p, dict)]
    if not isinstance(doc, dict):
        return []
    for key in ("archival_passages", "archival_memory", "passages"):
        value = doc.get(key)
        if isinstance(value, list):
            return [p for p in value if isinstance(p, dict)]
    agents = doc.get("agents")
    if isinstance(agents, list):
        return [p for agent in agents if isinstance(agent, dict) for p in _letta_passages(agent)]
    return []


# --- plain json -------------------------------------------------------------


def parse_json(doc: Any) -> list[SourceMemory]:
    """Anything else, as long as each record has some text.

    The escape hatch that makes the portability promise real: a format nobody
    has written a parser for is still importable with a two-line ``jq``, because
    this accepts any array of objects with a text-ish field.
    """
    out: list[SourceMemory] = []
    for record in _records(doc, ("memories", "results", "items", "data", "records")):
        body = _first(record, "body", "text", "content", "memory", "value")
        if not body:
            continue
        out.append(
            SourceMemory(
                body=body,
                title=_first(record, "title", "name") or _title_from(body),
                kind=_first(record, "kind", "type") or "fact",
                source_id=_first(record, "id", "public_id", "uuid"),
                metadata=_stamp(
                    "json",
                    record,
                    ("body", "text", "content", "memory", "value", "title", "name", "kind", "id"),
                ),
            )
        )
    if not out:
        raise UnreadableExportError(
            "no records with a text field (body/text/content/memory) were found"
        )
    return out


PARSERS = {
    "mem0": parse_mem0,
    "zep": parse_zep,
    "letta": parse_letta,
    "json": parse_json,
}


def parse_file(source: str, raw: str) -> list[SourceMemory]:
    """Parse ``raw`` as ``source``. Accepts JSON and JSONL alike.

    JSONL is checked first because a JSONL file of objects is not valid JSON,
    while a JSON array parses as one line and would be mis-split.
    """
    if source not in PARSERS:
        raise UnreadableExportError(
            f"unknown source {source!r}; expected one of {', '.join(PARSERS)}"
        )
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        doc = _load_jsonl(raw)
    return PARSERS[source](doc)


def _load_jsonl(raw: str) -> list[Any]:
    rows: list[Any] = []
    for number, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise UnreadableExportError(
                f"line {number} is neither valid JSON nor part of a JSON file: {e}"
            ) from e
    if not rows:
        raise UnreadableExportError("the file is empty, or is not JSON or JSONL")
    return rows
