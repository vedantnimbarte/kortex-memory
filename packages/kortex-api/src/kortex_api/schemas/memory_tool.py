"""Memory-tool proxy schemas."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from kortex_api.schemas.common import APIModel


class MemoryToolIn(APIModel):
    command: dict[str, Any]
    """The tool_use block's ``input``, verbatim.

    Not modelled field by field on purpose. This is Anthropic's contract, not
    ours: pinning a Pydantic union here would mean a new command or optional
    parameter is rejected at the door with a validation error rather than
    reaching the backend, which at least answers "unknown command" in a form
    Claude can read. The backend validates what it needs.
    """

    scope_type: str = "project"
    scope_id: int = 0
    sensitivity: str = "internal"
    """Applied to files this call creates. Bump it for a scope where an agent
    is working with material the whole org should not read back."""


class MemoryToolOut(APIModel):
    content: str
    """Put this in the ``tool_result`` block's ``content``."""
    is_error: bool = Field(default=False)
    """Set the same flag on the ``tool_result`` block."""
