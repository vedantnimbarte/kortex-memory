"""Search/recall tools.

``search_memory`` is plain hybrid retrieval; ``recall`` drives the agentic
planner/executor/reranker pipeline (with automatic fallback to hybrid when
the planner LLM isn't configured). ``get_context_bundle`` is just ``recall``
with ``synthesize=true``, surfaced as a named tool for clarity.
"""

from __future__ import annotations

from typing import Any

from kortex_core.db.types import ScopeType
from kortex_core.repositories.memory_repo import ScopeFilter
from kortex_core.services.agentic_retriever import (
    AgenticRetriever,
    RecallRequest,
)
from kortex_core.services.retrieval_service import RetrievalService, SearchRequest

from kortex_mcp.context import tool_context
from kortex_mcp.tools.base import ToolDef


async def _search_memory(args: dict[str, Any]) -> dict[str, Any]:
    async with tool_context() as (session, principal):
        scopes = _scopes(args)
        result = await RetrievalService(session, principal).search(
            SearchRequest(
                query=str(args["query"]),
                scopes=scopes,
                limit=int(args.get("limit", 20)),
                embed_query=bool(args.get("embed_query", True)),
            )
        )
        return {
            "used_vector": result.used_vector,
            "hits": [
                {
                    "public_id": h.public_id,
                    "title": h.title,
                    "body": h.body,
                    "tier": h.tier,
                    "sensitivity": h.sensitivity,
                    "importance": h.importance,
                    "decay_score": h.decay_score,
                    "pinned": h.pinned,
                    "score": h.score,
                }
                for h in result.hits
            ],
        }


async def _recall(args: dict[str, Any], *, synthesize: bool) -> dict[str, Any]:
    async with tool_context() as (session, principal):
        scopes = _scopes(args)
        retriever = AgenticRetriever(session, principal)
        bundle = await retriever.recall(
            RecallRequest(
                query=str(args["query"]),
                scopes=scopes,
                synthesize=synthesize or bool(args.get("synthesize", False)),
                max_tokens=int(args.get("max_tokens", 0)),
                per_item_max=int(args.get("per_item_max", 800)),
            )
        )
        return {
            "query": bundle.query,
            "answer": bundle.answer,
            "citations": [
                {"public_id": c.public_id, "title": c.title, "score": c.score}
                for c in bundle.citations
            ],
            "candidates": [
                {
                    "public_id": r.hit.public_id,
                    "title": r.hit.title,
                    "body": r.hit.body,
                    "tier": r.hit.tier,
                    "sensitivity": r.hit.sensitivity,
                    "final_score": r.final_score,
                    "rerank_score": r.rerank_score,
                }
                for r in bundle.candidates
            ],
            "used_tokens": bundle.used_tokens,
            "plan_trace": bundle.plan_trace,
            "plan_rationale": bundle.plan_rationale,
            "hops": bundle.hops,
            "stopped_reason": bundle.stopped_reason,
        }


def _scopes(args: dict[str, Any]) -> list[ScopeFilter] | None:
    raw = args.get("scopes")
    if not raw:
        return None
    return [
        ScopeFilter(
            scope_type=ScopeType(s["scope_type"]),
            scope_id=int(s["scope_id"]),
        )
        for s in raw
    ]


_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "scopes": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "required": ["scope_type", "scope_id"],
                "properties": {
                    "scope_type": {
                        "type": "string",
                        "enum": [s.value for s in ScopeType],
                    },
                    "scope_id": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            "default": None,
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        "embed_query": {"type": "boolean", "default": True},
    },
    "additionalProperties": False,
}


_RECALL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "minLength": 1},
        "scopes": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "required": ["scope_type", "scope_id"],
                "properties": {
                    "scope_type": {
                        "type": "string",
                        "enum": [s.value for s in ScopeType],
                    },
                    "scope_id": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            "default": None,
        },
        "synthesize": {"type": "boolean", "default": False},
        "max_tokens": {
            "type": "integer",
            "minimum": 0,
            "maximum": 32000,
            "default": 0,
        },
        "per_item_max": {
            "type": "integer",
            "minimum": 64,
            "maximum": 4000,
            "default": 800,
        },
    },
    "additionalProperties": False,
}


_SEARCH = ToolDef(
    name="search_memory",
    description=(
        "Hybrid retrieval over memories (pgvector + BM25, fused via RRF, "
        "decay-weighted). Sensitivity is bounded by caller's max-sensitivity."
    ),
    input_schema=_INPUT_SCHEMA,
    handler=_search_memory,
)


_RECALL = ToolDef(
    name="recall",
    description=(
        "Agentic recall: plans a multi-step retrieval, executes against the "
        "hybrid substrate + link graph, reranks, and returns a packed "
        "ContextBundle. Falls back to plain hybrid retrieval when the "
        "planner LLM is not configured."
    ),
    input_schema=_RECALL_SCHEMA,
    handler=lambda args: _recall(args, synthesize=False),
)


_CONTEXT_BUNDLE = ToolDef(
    name="get_context_bundle",
    description=(
        "Like `recall`, but also synthesizes a cited answer with the "
        "summarizer LLM. Returns the ContextBundle with `answer` populated."
    ),
    input_schema=_RECALL_SCHEMA,
    handler=lambda args: _recall(args, synthesize=True),
)


TOOLS: list[ToolDef] = [_SEARCH, _RECALL, _CONTEXT_BUNDLE]
