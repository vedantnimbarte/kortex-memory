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

from kortex_core.db.session import session_scope
from kortex_core.security.principal import (
    Principal,
    current_principal,
    reset_principal,
    set_principal,
)
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class McpRuntime:
    """Holds the bootstrapped principal for a *single-tenant* MCP process.

    Only the stdio transport uses this: it authenticates once at startup
    (``KORTEX_API_KEY``) and stashes the resulting Principal here, because a
    stdio process serves exactly one client. The SSE transport does NOT use this
    global — it binds a Principal per connection via the ``current_principal``
    context-var, so concurrent tenants can never collide.
    """

    principal: Principal


_runtime: McpRuntime | None = None


def set_runtime(runtime: McpRuntime) -> None:
    global _runtime
    _runtime = runtime


def get_runtime() -> McpRuntime:
    if _runtime is None:
        raise RuntimeError("MCP runtime not initialised — call set_runtime() before serving.")
    return _runtime


@asynccontextmanager
async def tool_context() -> AsyncIterator[tuple[AsyncSession, Principal]]:
    """Async context manager yielding ``(session, principal)`` to tool handlers.

    The principal is resolved from the per-connection context-var first (SSE
    binds it per connection); only if none is bound do we fall back to the
    single-tenant stdio runtime. If neither is present we raise — we never run a
    tool without an explicit principal, so a context-propagation failure fails
    closed (denied) rather than open (wrong tenant).
    """
    principal = current_principal()
    if principal is None:
        principal = _runtime.principal if _runtime is not None else None
    if principal is None:
        raise RuntimeError("no principal bound for MCP tool call — refusing to run unscoped")
    token = set_principal(principal)
    try:
        async with session_scope() as session:
            yield session, principal
    finally:
        reset_principal(token)
