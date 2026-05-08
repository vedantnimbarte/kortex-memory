"""Async engine and sessionmaker (lazy singletons)."""

from __future__ import annotations

from typing import Final

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from kortex_core.settings import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_DEFAULT_CONNECT_TIMEOUT: Final[int] = 10


def get_engine() -> AsyncEngine:
    """Return the lazily-constructed async engine."""
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url,
            echo=s.db_echo,
            pool_pre_ping=True,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_timeout=s.db_pool_timeout,
            connect_args={"timeout": _DEFAULT_CONNECT_TIMEOUT},
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the lazily-constructed sessionmaker."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def close_engine() -> None:
    """Dispose the engine (call on shutdown)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
