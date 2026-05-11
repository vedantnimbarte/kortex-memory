"""Unit tests for the API rate-limit bucket selector.

The middleware itself needs a Redis connection to exercise end-to-end. This
test pins the pure-function dispatching that decides which bucket a request
falls into so future router changes don't accidentally move recall traffic
into the larger read bucket (a common stealth-regression vector).
"""

from __future__ import annotations

from kortex_api.middleware.ratelimit import _bucket_for_path_method


def test_health_paths_are_unmetered() -> None:
    assert _bucket_for_path_method("/livez", "GET") is None
    assert _bucket_for_path_method("/readyz", "GET") is None
    assert _bucket_for_path_method("/metrics", "GET") is None


def test_recall_has_its_own_bucket() -> None:
    assert _bucket_for_path_method("/v1/search/recall", "POST") == "recall"


def test_reads_vs_writes() -> None:
    assert _bucket_for_path_method("/v1/memories", "GET") == "read"
    assert _bucket_for_path_method("/v1/memories", "POST") == "write"
    assert _bucket_for_path_method("/v1/memories/abc", "PATCH") == "write"
    assert _bucket_for_path_method("/v1/memories/abc", "DELETE") == "write"
