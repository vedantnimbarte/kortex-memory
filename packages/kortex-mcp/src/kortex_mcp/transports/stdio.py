"""Stdio transport: speak MCP over stdin/stdout.

Used by local AI coding agents (Claude Code, Codex, OpenCode) that launch the
MCP server as a subprocess and pass requests over pipes. Authentication is
read once from ``KORTEX_API_KEY`` at startup.
"""

from __future__ import annotations

import logging

from mcp.server.stdio import stdio_server

from kortex_core.db.engine import close_engine
from kortex_core.db.session import session_scope

from kortex_mcp.auth import principal_from_api_key, read_api_key_from_env
from kortex_mcp.context import McpRuntime, set_runtime
from kortex_mcp.server import build_server

logger = logging.getLogger(__name__)


async def run_stdio() -> None:
    """Run the MCP server over stdin/stdout until the client disconnects.

    Loads ``KORTEX_API_KEY``, materialises a Principal once via the
    ``AuthService``, stashes it in the process-wide runtime, then enters the
    stdio server loop. The DB engine is disposed on shutdown.
    """
    api_key = read_api_key_from_env()

    async with session_scope() as session:
        principal = await principal_from_api_key(session, api_key)
    set_runtime(McpRuntime(principal=principal))
    logger.info(
        "kortex_mcp.stdio.ready actor_id=%s org_id=%s",
        principal.actor_id,
        principal.org_id,
    )

    server = build_server()
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        await close_engine()
