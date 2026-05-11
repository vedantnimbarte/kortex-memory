"""Conversation summarizer skill.

Used by the ``generate_summary`` worker to write a one-paragraph summary of an
idle conversation back to ``Conversation.summary`` (and embed it later via
the existing ``embed_pending`` task).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol, runtime_checkable

from kortex_core.llm.protocol import LLM, LlmError, LlmMessage
from kortex_core.llm.registry import get_llm
from kortex_core.settings import get_settings


@runtime_checkable
class Summarizer(Protocol):
    name: str

    @abstractmethod
    async def summarize(
        self, messages: list[tuple[str, str]], *, max_words: int = 120
    ) -> str:
        ...


class LLMSummarizer(Summarizer):
    """Default impl — talks to the configured LLM provider."""

    name = "llm"

    def __init__(self, llm: LLM | None = None):
        self._llm = llm

    async def summarize(
        self, messages: list[tuple[str, str]], *, max_words: int = 120
    ) -> str:
        if not messages:
            return ""
        s = get_settings()
        llm = self._llm or get_llm(s.llm_provider)
        rendered = "\n".join(f"{role}: {content}" for role, content in messages)
        try:
            resp = await llm.complete(
                messages=[
                    LlmMessage(
                        role="system",
                        content=(
                            "Summarize the following conversation in at most "
                            f"{max_words} words. Be factual; skip pleasantries."
                        ),
                    ),
                    LlmMessage(role="user", content=rendered),
                ],
                model=s.llm_model_summarizer,
                max_tokens=max(200, max_words * 4),
                temperature=0.1,
            )
        except LlmError:
            return ""
        return resp.text.strip()


_singleton: Summarizer | None = None


def get_summarizer() -> Summarizer:
    global _singleton
    if _singleton is None:
        _singleton = LLMSummarizer()
    return _singleton
