"""MCP auth: materialize a Principal from a bearer credential.

The stdio transport reads ``KORTEX_API_KEY`` from the environment at startup
and binds the resulting principal for the lifetime of the process. The SSE
transport (M7) reuses :func:`principal_from_api_key` per-request from the
``Authorization: Bearer`` header.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.security.principal import Principal
from kortex_core.services.auth_service import AuthError, AuthService


class McpAuthError(Exception):
    """Raised when MCP auth fails (missing/invalid credential)."""


async def principal_from_api_key(session: AsyncSession, api_key: str) -> Principal:
    """Resolve a Principal from a plaintext ``kx_*`` API key."""
    try:
        load = await AuthService(session).principal_from_api_key(api_key)
    except AuthError as e:
        raise McpAuthError(f"invalid api key: {e}") from e
    return load.principal


def read_api_key_from_env() -> str:
    """Return ``KORTEX_API_KEY`` or raise McpAuthError if unset."""
    key = os.environ.get("KORTEX_API_KEY")
    if not key:
        raise McpAuthError(
            "KORTEX_API_KEY environment variable is required for the MCP stdio "
            "transport (a plaintext kx_* token minted via `kortex key create`)."
        )
    return key
