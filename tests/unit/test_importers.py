"""Competitor-export parsers.

**The fixtures here are synthetic.** They are built from each vendor's
documented API shapes, not captured from a real paid account, so these tests
prove the parsers behave as designed — not that the design matches what mem0
ships this week. That gap is why the command has a ``--dry-run`` and why every
unmapped field is kept rather than dropped.

What is worth testing, then, is the behaviour that survives a format change:
tolerance of the shapes we have seen, losslessness of the ones we have not, and
the two judgement calls (Zep's invalidated facts, Letta's core blocks) where the
parser decides something on the user's behalf.
"""

from __future__ import annotations

import json

import pytest
from kortex_cli.importers import (
    UnreadableExportError,
    parse_file,
    parse_json,
    parse_letta,
    parse_mem0,
    parse_zep,
)

# --- mem0 -------------------------------------------------------------------


def test_mem0_bare_list_and_results_wrapper_parse_the_same() -> None:
    """Which one you get depends on the client version, and a user migrating
    should not have to know which they have."""
    records = [{"id": "m1", "memory": "Alice prefers email follow-ups."}]

    assert parse_mem0(records)[0].body == parse_mem0({"results": records})[0].body


def test_mem0_keeps_what_it_cannot_map() -> None:
    """Categories, scores and user ids have no Kortex column. Dropping them is
    how a migration loses data nobody misses for six months."""
    [memory] = parse_mem0(
        [
            {
                "id": "m1",
                "memory": "Alice prefers email follow-ups.",
                "user_id": "alice",
                "categories": ["personal"],
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]
    )
    assert memory.metadata["imported_from"] == "mem0"
    assert memory.metadata["mem0"]["user_id"] == "alice"
    assert memory.metadata["mem0"]["categories"] == ["personal"]
    assert memory.source_id == "m1"


def test_mem0_categories_do_not_become_kinds() -> None:
    """mem0's category set is open and user-extensible; Kortex has seven fixed
    kinds. Mapping between them would mislabel silently, which is worse than
    not mapping at all."""
    [memory] = parse_mem0([{"memory": "x", "categories": ["food_preferences"]}])
    assert memory.kind == "fact"


def test_mem0_skips_records_with_no_text() -> None:
    assert parse_mem0([{"id": "m1"}, {"id": "m2", "memory": "real"}]) != []
    assert len(parse_mem0([{"id": "m1"}, {"id": "m2", "memory": "real"}])) == 1


# --- zep --------------------------------------------------------------------


def test_zep_imports_facts_not_transcripts() -> None:
    """Zep's value is the extracted edge, not the conversation it came from.
    Importing raw messages would flood the scope with noise the write path then
    has to decay away."""
    [memory] = parse_zep(
        {
            "facts": [{"uuid": "f1", "fact": "Acme renewed for 3 years."}],
            "messages": [{"role": "user", "content": "did acme renew?"}],
        }
    )
    assert memory.body == "Acme renewed for 3 years."
    assert memory.source_id == "f1"


def test_zep_skips_invalidated_facts() -> None:
    """Zep already decided these are superseded. Re-importing them would
    resurrect contradictions the source system had resolved."""
    memories = parse_zep(
        {
            "facts": [
                {"fact": "Acme is on the starter plan.", "invalid_at": "2026-02-01T00:00:00Z"},
                {"fact": "Acme is on the enterprise plan.", "invalid_at": None},
            ]
        }
    )
    assert [m.body for m in memories] == ["Acme is on the enterprise plan."]


def test_zep_reads_edges_as_well_as_facts() -> None:
    """v3 calls them edges; v2 called them facts. Same content."""
    assert parse_zep({"edges": [{"fact": "Alice manages Bob."}]})[0].body == "Alice manages Bob."


# --- letta ------------------------------------------------------------------


def test_letta_core_blocks_and_archival_passages_both_import() -> None:
    memories = parse_letta(
        {
            "blocks": [{"label": "human", "value": "The user is Alice, a backend engineer."}],
            "archival_passages": [{"id": "p1", "text": "The deploy runbook lives in ops/."}],
        }
    )
    assert len(memories) == 2
    assert memories[0].title == "letta:human"
    assert memories[1].body.startswith("The deploy runbook")


def test_letta_core_blocks_are_marked_for_pinning() -> None:
    """A core block is always in Letta's context by construction. It should not
    quietly decay out of Kortex's."""
    [block] = parse_letta({"blocks": [{"label": "persona", "value": "I am a support agent."}]})
    assert block.metadata["pinned_hint"] is True
    assert block.kind == "preference"


def test_letta_accepts_the_older_dict_shaped_core_memory() -> None:
    """Older agent files wrote {"persona": "...", "human": "..."} rather than a
    list of blocks."""
    memories = parse_letta({"core_memory": {"persona": "I am helpful.", "human": "Alice."}})
    assert {m.title for m in memories} == {"letta:persona", "letta:human"}


def test_letta_reaches_into_a_multi_agent_file() -> None:
    memories = parse_letta({"agents": [{"blocks": [{"label": "human", "value": "Alice."}]}]})
    assert memories[0].body == "Alice."


def test_letta_says_what_it_looked_for_when_it_finds_nothing() -> None:
    """An error that names the keys it wanted is a fixable error."""
    with pytest.raises(UnreadableExportError, match="archival_passages"):
        parse_letta({"something_else": []})


# --- plain json -------------------------------------------------------------


def test_json_accepts_any_array_of_objects_with_text() -> None:
    """The escape hatch that makes the portability promise real: a format
    nobody wrote a parser for is still importable after a two-line jq."""
    memories = parse_json([{"title": "Ledger", "body": "Postgres, for the joins."}])
    assert memories[0].title == "Ledger"
    assert memories[0].kind == "fact"


def test_json_honours_an_explicit_kind() -> None:
    assert parse_json([{"body": "x", "kind": "decision"}])[0].kind == "decision"


# --- shared behaviour -------------------------------------------------------


def test_a_missing_title_is_derived_from_the_body() -> None:
    """An empty title makes every row in a memory list look identical."""
    [memory] = parse_mem0([{"memory": "Alice prefers email.\nShe reads it at 9am."}])
    assert memory.title == "Alice prefers email."


def test_a_derived_title_is_truncated_on_a_word_boundary() -> None:
    long_body = "word " * 100
    [memory] = parse_mem0([{"memory": long_body}])
    assert len(memory.title) <= 200
    assert memory.title.endswith("…")


def test_jsonl_is_accepted_wherever_json_is() -> None:
    """Exports arrive both ways and the user should not have to care."""
    lines = "\n".join(json.dumps({"memory": f"fact {i}"}) for i in range(3))
    assert len(parse_file("mem0", lines)) == 3


def test_a_json_array_is_not_mistaken_for_jsonl() -> None:
    """A one-line JSON array would split into one bogus record if JSONL were
    tried first. Hence JSON first, JSONL as the fallback."""
    assert len(parse_file("mem0", json.dumps([{"memory": "a"}, {"memory": "b"}]))) == 2


def test_the_wrong_source_name_fails_by_naming_the_right_ones() -> None:
    with pytest.raises(UnreadableExportError, match="mem0"):
        parse_file("memzero", "[]")


def test_a_file_that_is_not_json_at_all_says_so() -> None:
    with pytest.raises(UnreadableExportError):
        parse_file("mem0", "this is not json")


def test_an_unrecognised_container_names_the_keys_it_wanted() -> None:
    with pytest.raises(UnreadableExportError, match="results"):
        parse_mem0({"rows": [{"memory": "x"}]})
