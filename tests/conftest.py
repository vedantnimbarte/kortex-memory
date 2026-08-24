"""Shared pytest fixtures.

Integration tests that need a real Postgres/Redis/MinIO use the testcontainers
fixtures in ``tests/integration/conftest.py``. Unit tests stay process-local.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-mark tests by directory so ``-m unit`` / ``-m integration`` pick up
    every file without each one having to remember ``pytestmark``. (A missing
    marker previously hid ~2/3 of the unit suite from CI.)
    """
    for item in items:
        # Normalise separators: on Windows ``fspath`` is backslash-delimited, so the
        # substring checks below silently matched nothing and ``-m unit`` selected
        # only the handful of files carrying an explicit ``pytestmark``.
        path = str(item.fspath).replace("\\", "/")
        if "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/tests/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/tests/e2e/" in path:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KORTEX_ENV", "test")
    monkeypatch.setenv("KORTEX_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("KORTEX_OTEL_ENABLED", "false")
