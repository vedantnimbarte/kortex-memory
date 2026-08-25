"""Amazon Bedrock LLM adapter.

Uses the **Converse** API rather than ``InvokeModel``: Converse takes one
message format across every model family and returns token usage in a uniform
shape, which is what recall's cost reporting reads. ``InvokeModel`` would mean
a per-family request builder and per-family usage parsing, re-earned for every
model an operator picks.

Structured output is the weak spot. Converse exposes tool-use for schema
enforcement, but support varies by model, so this adapter asks for JSON in the
system prompt and parses defensively — the same best-effort contract the Ollama
adapter documents. A caller that needs guaranteed structure should point at
Anthropic or OpenAI directly.
"""

from __future__ import annotations

import json
from typing import Any

from kortex_core.llm.protocol import LLM, LlmError, LlmMessage, LlmResponse
from kortex_core.settings import get_settings


def split_messages(messages: list[LlmMessage]) -> tuple[list[dict], list[dict]]:
    """Split into (system blocks, conversation turns).

    Converse takes the system prompt as a separate argument rather than a
    message with ``role="system"``, and rejects the latter.
    """
    system: list[dict] = []
    turns: list[dict] = []
    for message in messages:
        if message.role == "system":
            system.append({"text": message.content})
        else:
            turns.append({"role": message.role, "content": [{"text": message.content}]})
    return system, turns


def parse_response(payload: dict) -> tuple[str, int, int]:
    """Return (text, tokens_in, tokens_out) from a Converse response."""
    message = ((payload.get("output") or {}).get("message")) or {}
    text = "".join(block.get("text", "") for block in message.get("content") or [])
    usage = payload.get("usage") or {}
    return text, int(usage.get("inputTokens", 0)), int(usage.get("outputTokens", 0))


def extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON from a model that was merely asked nicely.

    Models wrap JSON in prose or fences often enough that a bare ``loads`` is
    not worth attempting alone. Returns None rather than raising: the callers
    here all treat missing structure as "fall back", not "fail".
    """
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("```")[1] if "```" in candidate[3:] else candidate[3:]
        candidate = candidate.removeprefix("json").strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


class BedrockLLM(LLM):
    provider = "bedrock"

    def __init__(self) -> None:
        self._region = get_settings().aws_region

    def _session_factory(self) -> Any:
        try:
            from aiobotocore.session import get_session
        except ImportError as e:  # pragma: no cover - optional extra
            raise LlmError(
                "aiobotocore not installed; install kortex-core[storage-s3] "
                "(Bedrock reuses the same AWS client stack)"
            ) from e
        return get_session()

    async def complete(
        self,
        messages: list[LlmMessage],
        *,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        json_schema: dict[str, Any] | None = None,
    ) -> LlmResponse:
        system, turns = split_messages(messages)
        if json_schema is not None:
            system.append(
                {
                    "text": (
                        "Reply with a single JSON object matching this schema and "
                        "nothing else — no prose, no code fences:\n"
                        f"{json.dumps(json_schema)}"
                    )
                }
            )

        session = self._session_factory()
        try:
            async with session.create_client("bedrock-runtime", region_name=self._region) as client:
                resp = await client.converse(
                    modelId=model,
                    messages=turns,
                    system=system or [{"text": "You are a helpful assistant."}],
                    inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
                )
        except Exception as e:
            raise LlmError(f"bedrock converse failed ({self._region}, {model}): {e}") from e

        text, tokens_in, tokens_out = parse_response(resp)
        return LlmResponse(
            text=text,
            structured=extract_json(text) if json_schema is not None else None,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
