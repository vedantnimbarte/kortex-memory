"""Unit tests for the ETag helper."""

from __future__ import annotations

from kortex_api.middleware.etag import etag_for_updated_at


def test_etag_is_stable_for_same_timestamp() -> None:
    a = etag_for_updated_at("2026-05-11T10:00:00+00:00")
    b = etag_for_updated_at("2026-05-11T10:00:00+00:00")
    assert a == b
    assert a.startswith('W/"')


def test_etag_changes_on_different_timestamp() -> None:
    a = etag_for_updated_at("2026-05-11T10:00:00+00:00")
    b = etag_for_updated_at("2026-05-11T10:00:01+00:00")
    assert a != b
