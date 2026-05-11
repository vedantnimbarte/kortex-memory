"""LLM Protocol — minimal, message-based, with structured-output via JSON schema.

The retrieval planner doesn't need streaming, vision, or batched tool calls;
it needs one synchronous-feeling round trip that returns structured JSON. The
summarizer is just text-in/text-out. Both fit under :class:`LLM`.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable


class LlmError(Exception):
    """Raised when an LLM call fails (network, auth, schema, etc.)."""


@dataclass(frozen=True, slots=True)
class LlmMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    """Final assistant text (after any tool round-trips, if applicable)."""

    structured: dict[str, Any] | None = None
    """Decoded JSON output when ``json_schema`` was requested."""

    model: str = ""
    """Model id used for the call (e.g. ``claude-sonnet-4-7``)."""

    tokens_in: int = 0
    tokens_out: int = 0


@runtime_checkable
class LLM(Protocol):
    """Minimum surface every LLM adapter must support."""

    provider: str
    """Stable provider id (``anthropic``, ``openai``, ``openrouter``, ``ollama``)."""

    @abstractmethod
    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        """Run one completion. If ``json_schema`` is set, the response should
        adhere to that schema (best-effort across providers).
        """
        ...
