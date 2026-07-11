"""Ollama adapter.

Talks to a local ``ollama serve`` instance over its OpenAI-compatible Chat API
(``/v1/chat/completions``). We use httpx directly to avoid pulling in another
SDK; JSON schema requests are sent as ``format="json"`` (Ollama best-effort).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from kortex_core.llm.protocol import LLM, LlmError, LlmMessage, LlmResponse
from kortex_core.settings import get_settings


class OllamaLLM(LLM):
    provider = "ollama"

    def __init__(self) -> None:
        s = get_settings()
        self._base_url = s.ollama_base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=120.0)

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_schema is not None:
            payload["format"] = "json"

        try:
            resp = await self._client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
        except Exception as e:
            raise LlmError(f"ollama call failed: {e}") from e
        data = resp.json()
        text = (data.get("message") or {}).get("content", "")
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
            tokens_in=int(data.get("prompt_eval_count") or 0),
            tokens_out=int(data.get("eval_count") or 0),
        )
