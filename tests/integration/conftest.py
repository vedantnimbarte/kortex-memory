"""Integration test fixtures (real Postgres + Redis via testcontainers)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    """Provide a Postgres URL. Prefers the CI ``KORTEX_DATABASE_URL`` env."""
    if env_url := os.environ.get("KORTEX_DATABASE_URL"):
        yield env_url
        return

    pytest.importorskip("testcontainers.postgres")
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer(
        "pgvector/pgvector:pg16", username="kortex", password="kortex", dbname="kortex"
    )
    container.start()
    try:
        url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )
        yield url
    finally:
        container.stop()


@pytest.fixture(scope="session", autouse=True)
def _alembic_upgrade(pg_url: str, monkeypatch_session: pytest.MonkeyPatch) -> None:
    monkeypatch_session.setenv("KORTEX_DATABASE_URL", pg_url)
    subprocess.run(["alembic", "upgrade", "head"], check=True)


@pytest.fixture(scope="session")
def monkeypatch_session() -> Iterator[pytest.MonkeyPatch]:
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest_asyncio.fixture
async def session(pg_url: str) -> AsyncIterator:
    from kortex_core.db.engine import close_engine
    from kortex_core.db.session import session_scope

    async with session_scope() as s:
        yield s
    await close_engine()
