"""Sentence-aware chunker.

We don't import a tokenizer (1 token ≈ 4 chars heuristic is good enough for
chunking). The chunker greedily fills chunks up to ``max_tokens``, with
``overlap`` tokens of context carried into the next chunk. Sentence boundaries
are preferred but never blocking.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_SENT_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n\n+")


def _chars_per_token() -> int:
    return 4


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + _chars_per_token() - 1) // _chars_per_token())


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_BOUNDARY.split(text) if p and p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def chunk_text(
    text: str,
    *,
    max_tokens: int = 512,
    overlap_tokens: int = 64,
) -> Iterable[tuple[int, str]]:
    """Yield ``(chunk_index, content)`` greedily fitting ``max_tokens`` each.

    Sentence boundaries are preferred for break points; if a single sentence
    exceeds ``max_tokens``, it is hard-split at character boundaries so a
    pathologically long line never produces a single 5MB chunk.
    """
    if not text or not text.strip():
        return
    cpt = _chars_per_token()
    max_chars = max_tokens * cpt
    overlap_chars = overlap_tokens * cpt

    sentences = _split_sentences(text)
    chunk_index = 0
    buffer: list[str] = []
    buffer_chars = 0

    def flush() -> tuple[int, str] | None:
        nonlocal chunk_index
        nonlocal buffer
        nonlocal buffer_chars
        if not buffer:
            return None
        body = " ".join(buffer).strip()
        idx = chunk_index
        chunk_index += 1
        # Build the carry-over tail for overlap.
        tail = body[-overlap_chars:] if overlap_chars > 0 else ""
        buffer = [tail] if tail else []
        buffer_chars = len(tail)
        return idx, body

    for sentence in sentences:
        sent_chars = len(sentence)
        if sent_chars > max_chars:
            # Hard-split very long sentences.
            for i in range(0, sent_chars, max_chars):
                piece = sentence[i : i + max_chars]
                if buffer_chars + len(piece) + 1 > max_chars and buffer:
                    out = flush()
                    if out:
                        yield out
                buffer.append(piece)
                buffer_chars += len(piece) + 1
                if buffer_chars >= max_chars:
                    out = flush()
                    if out:
                        yield out
            continue

        if buffer_chars + sent_chars + 1 > max_chars and buffer:
            out = flush()
            if out:
                yield out
        buffer.append(sentence)
        buffer_chars += sent_chars + 1

    out = flush()
    if out:
        yield out


def _est(text: str) -> int:
    """Public helper for tests."""
    return _estimate_tokens(text)
