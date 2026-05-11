"""Tool registry primitives.

Each MCP tool is a :class:`ToolDef` (name + JSON schema + async handler). Tool
handlers return JSON-serialisable Python values; the server is responsible for
wrapping them in MCP ``TextContent`` blocks.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[Any]]


def json_default(value: Any) -> Any:
    """``json.dumps`` default that handles UUID/datetime/Enum gracefully."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def all_tools() -> list[ToolDef]:
    """Aggregate every tool module's ``TOOLS`` into a single registry."""
    from kortex_mcp.tools import attachments, memory, search, session

    return [
        *memory.TOOLS,
        *search.TOOLS,
        *session.TOOLS,
        *attachments.TOOLS,
    ]
