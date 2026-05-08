"""Shared pytest fixtures.

Integration tests that need a real Postgres/Redis/MinIO use the testcontainers
fixtures in ``tests/integration/conftest.py``. Unit tests stay process-local.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KORTEX_ENV", "test")
    monkeypatch.setenv("KORTEX_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("KORTEX_OTEL_ENABLED", "false")
