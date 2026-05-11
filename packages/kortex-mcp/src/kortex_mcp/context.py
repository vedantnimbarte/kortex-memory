"""Per-tool-call context: DB session + bound principal.

Every MCP tool needs:

  * an async SQLAlchemy session (commits on success, rolls back on error)
  * a Principal bound to the context-var so repositories/services pick it up

This module gives tools one async context manager that wires both up.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.session import session_scope
from kortex_core.security.principal import (
    Principal,
    reset_principal,
    set_principal,
)


@dataclass(frozen=True, slots=True)
class McpRuntime:
    """Holds the bootstrapped principal for the running MCP server.

    The stdio transport authenticates once at startup (``KORTEX_API_KEY``) and
    stashes the resulting Principal here. SSE will instead resolve a Principal
    per-connection in its handshake (M7).
    """

    principal: Principal


_runtime: McpRuntime | None = None


def set_runtime(runtime: McpRuntime) -> None:
    global _runtime
    _runtime = runtime


def get_runtime() -> McpRuntime:
    if _runtime is None:
        raise RuntimeError(
            "MCP runtime not initialised — call set_runtime() before serving."
        )
    return _runtime


@asynccontextmanager
async def tool_context() -> AsyncIterator[tuple[AsyncSession, Principal]]:
    """Async context manager yielding ``(session, principal)`` to tool handlers.

    On enter: binds the principal to the context-var (so repositories see it),
    opens an AsyncSession. On exit: commits the session (or rolls back) and
    resets the context-var.
    """
    runtime = get_runtime()
    token = set_principal(runtime.principal)
    try:
        async with session_scope() as session:
            yield session, runtime.principal
    finally:
        reset_principal(token)
