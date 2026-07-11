"""Anthropic adapter (default planner/summarizer).

Uses the Anthropic SDK's Messages API and (when a JSON schema is supplied)
constructs a single tool-call that the model must invoke, capturing the
tool input as structured output. Falls back to a plain text completion when no
schema is requested.
"""

from __future__ import annotations

import json
from typing import Any

from kortex_core.llm.protocol import LLM, LlmError, LlmMessage, LlmResponse
from kortex_core.settings import get_settings


def _import_anthropic() -> Any:
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover - optional dep
        raise LlmError("anthropic SDK not installed; install kortex-core[llm-anthropic]") from e
    return anthropic


class AnthropicLLM(LLM):
    provider = "anthropic"

    def __init__(self) -> None:
        s = get_settings()
        key = s.anthropic_api_key
        if key is None:
            raise LlmError("KORTEX_ANTHROPIC_API_KEY not configured")
        anthropic = _import_anthropic()
        self._client = anthropic.AsyncAnthropic(api_key=key.get_secret_value())

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        convo = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in {"user", "assistant"}
        ]

        if json_schema is not None:
            # Single-tool trick: define one tool whose input matches the
            # schema, force the model to call it, then read the tool input.
            tool = {
                "name": "respond",
                "description": "Provide the response in the required schema.",
                "input_schema": json_schema,
            }
            try:
                resp = await self._client.messages.create(
                    model=model,
                    system=system or None,
                    messages=convo,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": "respond"},
                )
            except Exception as e:
                raise LlmError(f"anthropic call failed: {e}") from e

            structured: dict[str, Any] | None = None
            text_chunks: list[str] = []
            for block in resp.content:
                btype = getattr(block, "type", None)
                if btype == "tool_use" and getattr(block, "name", "") == "respond":
                    raw = getattr(block, "input", None)
                    structured = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                elif btype == "text":
                    text_chunks.append(getattr(block, "text", ""))
            return LlmResponse(
                text="\n".join(text_chunks),
                structured=structured,
                model=model,
                tokens_in=int(getattr(resp.usage, "input_tokens", 0) or 0),
                tokens_out=int(getattr(resp.usage, "output_tokens", 0) or 0),
            )

        try:
            resp = await self._client.messages.create(
                model=model,
                system=system or None,
                messages=convo,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            raise LlmError(f"anthropic call failed: {e}") from e

        text = "".join(
            getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
        )
        return LlmResponse(
            text=text,
            model=model,
            tokens_in=int(getattr(resp.usage, "input_tokens", 0) or 0),
            tokens_out=int(getattr(resp.usage, "output_tokens", 0) or 0),
        )
