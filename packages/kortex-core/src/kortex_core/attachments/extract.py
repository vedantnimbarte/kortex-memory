"""Text extraction from common document formats.

Strategy is deliberately conservative: we only depend on libraries that are
small and battle-tested (PyMuPDF for PDF, python-docx for .docx). Anything we
can't recognise is treated as utf-8 text. Real plain text and markdown pass
through unchanged.
"""

from __future__ import annotations

import io
from typing import Final

_MIME_PLAIN: Final = {
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "text/csv",
    "application/json",
}


class ExtractionError(Exception):
    """Raised when text extraction fails for a known mime."""


def extract_text(body: bytes, *, mime: str | None = None, filename: str = "") -> str:
    """Best-effort text extraction. Returns ``""`` if no content can be parsed.

    Parameters
    ----------
    body:
        Raw object bytes.
    mime:
        Optional content type hint. If absent, we infer from the filename.
    filename:
        Optional filename. Used to pick a parser when ``mime`` is missing.
    """
    mime = (mime or "").lower()
    name = filename.lower()

    if mime == "application/pdf" or name.endswith(".pdf"):
        return _extract_pdf(body)
    if (
        mime
        in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        or name.endswith(".docx")
    ):
        return _extract_docx(body)
    if mime in _MIME_PLAIN or any(
        name.endswith(ext) for ext in (".txt", ".md", ".markdown", ".csv", ".json")
    ):
        return _decode_text(body)

    # Fallback: try decoding as utf-8 text.
    try:
        return _decode_text(body)
    except UnicodeDecodeError:
        return ""


def _decode_text(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def _extract_pdf(body: bytes) -> str:
    try:
        import pymupdf  # PyMuPDF >= 1.24 exposes the top-level ``pymupdf`` module.
    except ImportError as e:  # pragma: no cover - optional dep
        raise ExtractionError(
            "PyMuPDF not installed; install kortex-core[attachments]"
        ) from e

    try:
        with pymupdf.open(stream=body, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc)
    except Exception as e:  # noqa: BLE001
        raise ExtractionError(f"pdf extraction failed: {e}") from e


def _extract_docx(body: bytes) -> str:
    try:
        from docx import Document  # python-docx
    except ImportError as e:  # pragma: no cover - optional dep
        raise ExtractionError(
            "python-docx not installed; install kortex-core[attachments]"
        ) from e

    try:
        doc = Document(io.BytesIO(body))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:  # noqa: BLE001
        raise ExtractionError(f"docx extraction failed: {e}") from e
