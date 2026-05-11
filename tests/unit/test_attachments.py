"""Unit tests for the attachment chunker + extractor + FS blob store.

These run process-local — no Postgres, no S3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kortex_core.attachments.chunker import chunk_text
from kortex_core.attachments.extract import extract_text
from kortex_core.storage.fs import FilesystemBlobStore


def test_chunker_packs_within_budget() -> None:
    text = ". ".join(f"sentence number {i}" for i in range(60)) + "."
    chunks = list(chunk_text(text, max_tokens=64, overlap_tokens=8))
    assert len(chunks) >= 2
    # Indices monotonically increasing from 0.
    assert [i for i, _ in chunks] == list(range(len(chunks)))
    # No chunk wildly exceeds budget (allow some slack from sentence boundaries).
    for _, content in chunks:
        assert len(content) <= 64 * 4 * 2  # 2x slack for sentence-aware packing


def test_chunker_empty_input() -> None:
    assert list(chunk_text("")) == []
    assert list(chunk_text("   \n  ")) == []


def test_chunker_hard_splits_one_giant_sentence() -> None:
    huge = "a" * 5000
    chunks = list(chunk_text(huge, max_tokens=64, overlap_tokens=0))
    assert len(chunks) > 1
    assert "".join(c for _, c in chunks).count("a") >= 5000


def test_extract_text_plain_passthrough() -> None:
    body = b"Hello, world.\nThis is markdown."
    assert "Hello, world." in extract_text(body, mime="text/markdown", filename="x.md")


def test_extract_text_unknown_mime_falls_back_to_utf8() -> None:
    body = "free-text content".encode()
    assert "free-text" in extract_text(body, mime=None, filename="notes.txt")


async def test_fs_blob_store_roundtrip(tmp_path: Path) -> None:
    store = FilesystemBlobStore(root=str(tmp_path))
    meta = await store.put_bytes(
        bucket="b", key="alpha/beta.txt", body=b"hi", content_type="text/plain"
    )
    assert meta.size_bytes == 2
    assert meta.sha256 is not None and len(meta.sha256) == 64

    head = await store.head(bucket="b", key="alpha/beta.txt")
    assert head is not None and head.size_bytes == 2

    body = await store.get_bytes(bucket="b", key="alpha/beta.txt")
    assert body == b"hi"

    assert await store.delete(bucket="b", key="alpha/beta.txt") is True
    assert await store.head(bucket="b", key="alpha/beta.txt") is None


async def test_fs_blob_store_presign_returns_file_url(tmp_path: Path) -> None:
    store = FilesystemBlobStore(root=str(tmp_path))
    upload = await store.presign_put(bucket="b", key="x.txt")
    assert upload.method == "PUT"
    assert upload.url.startswith("file://")


@pytest.mark.parametrize("filename,mime", [("doc.pdf", "application/pdf")])
def test_extract_text_pdf_missing_dependency_returns_extraction_error(
    filename: str, mime: str
) -> None:
    """PDF extraction requires PyMuPDF — exercise the unhappy path safely.

    We don't ship PyMuPDF in core; the test asserts that the failure mode is a
    clean ExtractionError rather than an arbitrary ImportError leaking out.
    """
    from kortex_core.attachments.extract import ExtractionError

    try:
        import pymupdf  # noqa: F401

        pytest.skip("pymupdf is installed; happy path is exercised by integration tests")
    except ImportError:
        pass

    with pytest.raises(ExtractionError):
        extract_text(b"%PDF-1.4 garbage", mime=mime, filename=filename)
