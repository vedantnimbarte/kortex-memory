"""MCP tools, grouped by domain.

Each module exposes a ``TOOLS`` list of :class:`ToolDef`. The server glues them
together into one registry so that stdio and SSE share the exact same surface.
"""

from __future__ import annotations

from kortex_mcp.tools.base import ToolDef, all_tools

__all__ = ["ToolDef", "all_tools"]
