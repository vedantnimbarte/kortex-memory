"""Content fingerprinting for write-time deduplication.

Agents re-remember things. The same fact gets written on Monday and again on
Friday, a retried request stores its payload twice, an ingest re-runs over a
git log it has already seen. Every copy then competes for space in the same
recall result, so the caller pays context tokens to read the same sentence
three times — which is the complaint behind "duplicates per query" being the
headline number competing memory systems advertise.

This is the cheap half of the answer: an exact fingerprint of the normalised
content, checked before insert. It catches verbatim repeats and retries, which
is most of them, and it needs no embedding — so it works synchronously on the
write path, where the caller can still be told what happened.

It deliberately does **not** catch paraphrases. "We use Redis for the queue"
and "the queue runs on Redis" have different fingerprints and both get stored.
Catching those needs a vector comparison, which needs an embedding, which does
not exist until the worker has run. That belongs in the deferred pass beside
conflict detection, not here.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")

_FIELD_SEPARATOR = "\x1f"
"""ASCII unit separator. Hashing title and body with a delimiter that cannot
occur in normalised text stops ("ab", "") and ("a", "b") colliding."""

HASH_LENGTH = 64
"""Hex characters in a SHA-256 digest — the column width."""


def normalize_content(text: str) -> str:
    """Collapse the differences that do not change what a memory says.

    Unicode is folded to NFKC and runs of whitespace become single spaces, so
    reflowed or re-indented text fingerprints identically. **Case is
    preserved**: in a memory layer holding identifiers, config keys and code,
    ``DEBUG`` and ``debug`` are not reliably the same thing, and merging them
    would silently lose the distinction.
    """
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def content_hash(title: str, body: str) -> str:
    """Stable fingerprint of a memory's user-visible content.

    Only title and body participate. Two memories that say the same thing but
    carry different importance, tier or metadata are the same memory written
    twice, and the duplicate's metadata is merged into the survivor rather than
    making it a separate row.
    """
    payload = f"{normalize_content(title)}{_FIELD_SEPARATOR}{normalize_content(body)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
