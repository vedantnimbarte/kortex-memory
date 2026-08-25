"""Content fingerprinting for write-time dedup.

The fingerprint decides whether two writes are the same memory. Too eager and
distinct facts get silently merged, which loses data with no trace; too timid
and duplicates pile up in every recall result. These tests pin exactly where
that line sits.
"""

from __future__ import annotations

import pytest
from kortex_core.dedup import HASH_LENGTH, content_hash, normalize_content

# --- normalisation: what should be treated as the same text ---


def test_identical_text_normalises_identically() -> None:
    assert normalize_content("the queue runs on Redis") == "the queue runs on Redis"


@pytest.mark.parametrize(
    "text",
    [
        "  the queue runs on Redis  ",
        "the queue  runs   on Redis",
        "the queue\nruns\ton Redis",
        "\n\nthe queue runs on Redis\n",
    ],
)
def test_whitespace_differences_are_folded_away(text: str) -> None:
    """Reflowed or re-indented text is the same memory."""
    assert normalize_content(text) == "the queue runs on Redis"


def test_unicode_is_folded_to_nfkc() -> None:
    """Composed and decomposed forms of the same character are one memory.

    Spelled with explicit codepoints rather than literal accents: an editor
    that normalised this file would quietly collapse the two spellings and
    leave behind a test that cannot fail.
    """
    composed = "café"  # e-acute as a single codepoint
    decomposed = "café"  # plain e followed by a combining acute
    assert composed != decomposed, "the two spellings must actually differ"
    assert normalize_content(composed) == normalize_content(decomposed)
    assert content_hash("", composed) == content_hash("", decomposed)


def test_case_is_preserved() -> None:
    """A memory layer holds identifiers, config keys and code. DEBUG and debug
    are not reliably the same thing, and merging them loses the distinction."""
    assert normalize_content("DEBUG") != normalize_content("debug")


def test_empty_text_normalises_to_empty() -> None:
    assert normalize_content("") == ""
    assert normalize_content("   \n\t ") == ""


# --- hashing ---


def test_hash_is_stable_across_calls() -> None:
    assert content_hash("t", "b") == content_hash("t", "b")


def test_hash_is_a_full_sha256_hex_digest() -> None:
    digest = content_hash("t", "b")
    assert len(digest) == HASH_LENGTH
    assert set(digest) <= set("0123456789abcdef")


def test_reformatted_content_hashes_the_same() -> None:
    assert content_hash("Queue", "runs on Redis") == content_hash("  Queue ", "runs   on\nRedis")


def test_different_body_hashes_differently() -> None:
    assert content_hash("t", "runs on Redis") != content_hash("t", "runs on Postgres")


def test_different_title_hashes_differently() -> None:
    """Same body under a different heading is a different memory."""
    assert content_hash("queue", "b") != content_hash("cache", "b")


def test_title_and_body_cannot_bleed_into_each_other() -> None:
    """Without a delimiter, ("ab", "") and ("a", "b") would collide and two
    unrelated memories would silently merge."""
    assert content_hash("ab", "") != content_hash("a", "b")


def test_a_paraphrase_is_not_a_duplicate() -> None:
    """Documented limitation, pinned so it is a decision rather than a
    surprise: catching paraphrases needs a vector, which needs an embedding,
    which does not exist on the write path."""
    assert content_hash("", "We use Redis for the queue") != content_hash(
        "", "The queue runs on Redis"
    )
