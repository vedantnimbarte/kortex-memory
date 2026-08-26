"""Path handling and output formatting for the Claude memory-tool backend.

Path validation is the security boundary: Anthropic's own documentation makes
it the implementer's responsibility, and every command goes through it. It is
also pure, so it is tested here rather than behind a database.

The formatting matters more than it looks. Claude reads line numbers out of a
``view`` and feeds them back as ``insert_line``. Numbering that is off by one,
or that restarts at 1 for a windowed view, sends the next edit to the wrong
place — and nothing errors, the file just quietly ends up wrong.
"""

from __future__ import annotations

import pytest
from kortex_core.memory_tool import (
    MEMORY_ROOT,
    _human_size,
    _numbered,
    _RejectedError,
    _slice,
    normalise_path,
)

# --- the security boundary --------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "/memories/../secrets.env",
        "/memories/a/../../etc/shadow",
        "../memories/x",
        "/memorie",
        "/memoriesX/y",
        "memories/x",
    ],
)
def test_paths_outside_the_memory_root_are_refused(path: str) -> None:
    with pytest.raises(_RejectedError):
        normalise_path(path)


@pytest.mark.parametrize("path", ["/memories/%2e%2e/x", "/memories/%2E%2E%2Fx", "/memories/a%5Cb"])
def test_percent_encoded_traversal_is_refused_rather_than_decoded(path: str) -> None:
    """Nothing legitimate sends this, so its presence means someone is probing.
    Decoding it first would be doing the attacker's work."""
    with pytest.raises(_RejectedError):
        normalise_path(path)


def test_backslashes_are_refused() -> None:
    with pytest.raises(_RejectedError):
        normalise_path("/memories/a\\..\\b")


@pytest.mark.parametrize("path", [None, "", "   ", 42, ["/memories/x"]])
def test_a_missing_or_non_string_path_is_refused(path: object) -> None:
    with pytest.raises(_RejectedError):
        normalise_path(path)


# --- canonicalisation: a correctness bug before it is a security one --------


def test_equivalent_paths_canonicalise_to_one_key() -> None:
    """Without this, /memories/a/../b and /memories/b are two different rows.
    Claude writes to one, reads back the other, and its memory appears to have
    been lost with nothing in any log to say why."""
    assert normalise_path("/memories/./notes.md") == "/memories/notes.md"
    assert normalise_path("/memories//notes.md") == "/memories/notes.md"
    assert normalise_path("/memories/sub/./notes.md") == "/memories/sub/notes.md"


def test_trailing_whitespace_does_not_make_a_second_file() -> None:
    assert normalise_path("  /memories/notes.md  ") == "/memories/notes.md"


def test_the_root_itself_is_a_valid_path() -> None:
    assert normalise_path(MEMORY_ROOT) == MEMORY_ROOT


def test_nested_paths_are_allowed() -> None:
    assert normalise_path("/memories/project/decisions.md") == "/memories/project/decisions.md"


# --- formatting Claude then acts on ----------------------------------------


def test_line_numbers_are_six_wide_right_aligned_and_one_indexed() -> None:
    assert _numbered("alpha\nbeta") == "     1\talpha\n     2\tbeta"


def test_a_windowed_view_keeps_absolute_line_numbers() -> None:
    """Renumbering a slice from 1 is a lie Claude acts on: its next insert_line
    would land somewhere else entirely."""
    body = "\n".join(f"line {i}" for i in range(1, 11))
    text, first = _slice(body, [4, 6])

    assert text == "line 4\nline 5\nline 6"
    assert _numbered(text, first=first).startswith("     4\tline 4")


def test_minus_one_means_to_the_end() -> None:
    body = "a\nb\nc\nd"
    assert _slice(body, [3, -1]) == ("c\nd", 3)


def test_an_out_of_range_window_clamps_rather_than_erroring() -> None:
    body = "a\nb"
    assert _slice(body, [1, 99]) == ("a\nb", 1)


def test_a_nonsense_window_falls_back_to_the_whole_file() -> None:
    """Claude asked to read something. Reading all of it is a more useful answer
    than a complaint about indices."""
    assert _slice("a\nb", ["x", "y"]) == ("a\nb", 1)
    assert _slice("a\nb", [9, 2]) == ("a\nb", 1)


def test_sizes_are_human_readable() -> None:
    assert _human_size("") == "1"
    assert _human_size("x" * 512) == "512"
    assert _human_size("x" * 2048) == "2.0K"
    assert _human_size("x" * (3 * 1024 * 1024)) == "3.0M"
