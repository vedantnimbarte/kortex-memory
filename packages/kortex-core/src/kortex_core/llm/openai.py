"""OpenAI adapter.

Uses the Chat Completions API with ``response_format={"type":"json_schema"}``
for structured output. Plain text completions skip ``response_format``.
"""

from __future__ import annotations

import json
from typing import Any

from kortex_core.llm.protocol import LLM, LlmError, LlmMessage, LlmResponse
from kortex_core.settings import get_settings


def _import_openai() -> Any:
    try:
        import openai
    except ImportError as e:  # pragma: no cover - optional dep
        raise LlmError("openai SDK not installed; install kortex-core[llm-openai]") from e
    return openai


class OpenAILLM(LLM):
    provider = "openai"

    def __init__(self) -> None:
        s = get_settings()
        key = s.openai_api_key
        if key is None:
            raise LlmError("KORTEX_OPENAI_API_KEY not configured")
        openai = _import_openai()
        self._client = openai.AsyncOpenAI(api_key=key.get_secret_value())

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        msgs = [{"role": m.role, "content": m.content} for m in messages]
        kw: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_schema is not None:
            kw["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "respond",
                    "schema": json_schema,
                    "strict": True,
                },
            }
        try:
            resp = await self._client.chat.completions.create(**kw)
        except Exception as e:
            raise LlmError(f"openai call failed: {e}") from e

        choice = resp.choices[0].message
        text = choice.content or ""
        structured: dict[str, Any] | None = None
        if json_schema is not None and text:
            try:
                structured = json.loads(text)
            except json.JSONDecodeError:
                structured = None
        return LlmResponse(
            text=text,
            structured=structured,
            model=model,
            tokens_in=int(getattr(resp.usage, "prompt_tokens", 0) or 0),
            tokens_out=int(getattr(resp.usage, "completion_tokens", 0) or 0),
        )
