"""Mid-tier consolidator.

``LLMConsolidator`` takes a cluster of mid-tier memories that share a topic and
asks the configured LLM to write one long-tier summary memory. The new memory
is returned as a structured payload; the worker persists it and rolls
``derived_from`` links back to the source memories.

Clustering is done by the worker (HDBSCAN over BGE embeddings); this skill
focuses on the language-model side so cluster strategies can swap.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from kortex_core.llm.protocol import LLM, LlmError, LlmMessage
from kortex_core.llm.registry import get_llm
from kortex_core.settings import get_settings


@dataclass(frozen=True, slots=True)
class ClusterMember:
    memory_id: int
    public_id: str
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class ConsolidationResult:
    title: str
    body: str
    derived_from_ids: list[int]


@runtime_checkable
class Consolidator(Protocol):
    name: str

    @abstractmethod
    async def consolidate(self, cluster: list[ClusterMember]) -> ConsolidationResult | None: ...


_SYSTEM = (
    "You are consolidating short/mid-term memories into one long-term summary. "
    "Read the cluster, then output a single concise memory that captures the "
    "common subject. Title <= 60 chars. Body <= 400 words. Avoid invented "
    "facts; if there is disagreement, note it. Never include identifiers."
)


class LLMConsolidator(Consolidator):
    name = "llm"

    def __init__(self, llm: LLM | None = None):
        self._llm = llm

    async def consolidate(self, cluster: list[ClusterMember]) -> ConsolidationResult | None:
        if not cluster:
            return None
        s = get_settings()
        llm = self._llm or get_llm(s.llm_provider)

        rendered = "\n\n---\n\n".join(f"{m.title}\n{m.body}" for m in cluster)

        schema = {
            "type": "object",
            "required": ["title", "body"],
            "properties": {
                "title": {"type": "string", "maxLength": 60},
                "body": {"type": "string", "maxLength": 4000},
            },
            "additionalProperties": False,
        }

        try:
            resp = await llm.complete(
                messages=[
                    LlmMessage(role="system", content=_SYSTEM),
                    LlmMessage(role="user", content=rendered),
                ],
                model=s.llm_model_summarizer,
                max_tokens=800,
                temperature=0.1,
                json_schema=schema,
            )
        except LlmError:
            return None

        payload = resp.structured or {}
        title = (payload.get("title") or "").strip()
        body = (payload.get("body") or resp.text or "").strip()
        if not body:
            return None
        return ConsolidationResult(
            title=title or "consolidated summary",
            body=body,
            derived_from_ids=[m.memory_id for m in cluster],
        )


_singleton: Consolidator | None = None


def get_consolidator() -> Consolidator:
    global _singleton
    if _singleton is None:
        _singleton = LLMConsolidator()
    return _singleton
