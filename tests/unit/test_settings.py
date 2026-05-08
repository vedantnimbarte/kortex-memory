"""Settings load + override tests."""

from __future__ import annotations

import pytest

from kortex_core.settings.config import KortexSettings

pytestmark = pytest.mark.unit


def test_defaults_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KORTEX_DATABASE_URL", "postgresql+asyncpg://x:y@h:5432/d")
    s = KortexSettings()
    assert s.database_url == "postgresql+asyncpg://x:y@h:5432/d"
    assert s.embedder == "local_bge"
    assert s.embedder_dim == 1024
    assert s.agentic_retrieval is True


def test_cors_origins_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "KORTEX_API_CORS_ORIGINS", "http://a.test, http://b.test,http://c.test"
    )
    s = KortexSettings()
    assert s.api_cors_origins == ["http://a.test", "http://b.test", "http://c.test"]
