"""Kortex MCP server.

Builds the canonical :class:`mcp.server.Server` instance and registers every
tool exposed by :mod:`kortex_mcp.tools`. The same server object is reused by
both the stdio transport (this milestone) and the SSE transport (M7); transports
are thin wrappers that hand the same server to the appropriate ``mcp.server``
runner.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from kortex_mcp.tools import ToolDef, all_tools
from kortex_mcp.tools.base import json_default

logger = logging.getLogger(__name__)

SERVER_NAME = "kortex-memory"
SERVER_VERSION = "0.1.0"


def _to_mcp_tool(t: ToolDef) -> Tool:
    return Tool(name=t.name, description=t.description, inputSchema=t.input_schema)


def _serialise(value: Any) -> str:
    """Encode a tool result as the JSON text payload of a ``TextContent`` block."""
    return json.dumps(value, default=json_default, ensure_ascii=False)


def build_server() -> Server:
    """Construct the canonical Kortex MCP server with tools registered.

    Tool resolution is done eagerly at startup so unknown tool names fail
    fast rather than per-call.
    """
    server: Server = Server(SERVER_NAME, version=SERVER_VERSION)
    tools: dict[str, ToolDef] = {t.name: t for t in all_tools()}

    @server.list_tools()
    async def _list_tools() -> list[Tool]:  # pragma: no cover - thin shim
        return [_to_mcp_tool(t) for t in tools.values()]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        tool = tools.get(name)
        if tool is None:
            raise ValueError(f"unknown tool: {name}")
        try:
            result = await tool.handler(arguments or {})
        except Exception as e:
            logger.exception("kortex_mcp.tool_error name=%s", name)
            return [
                TextContent(
                    type="text",
                    text=_serialise({"error": type(e).__name__, "message": str(e)}),
                )
            ]
        return [TextContent(type="text", text=_serialise(result))]

    return server


__all__ = ["SERVER_NAME", "SERVER_VERSION", "build_server"]
