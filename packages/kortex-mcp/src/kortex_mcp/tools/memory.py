"""Memory CRUD tools: remember, get, list, update, delete, link, pin."""

from __future__ import annotations

import uuid
from typing import Any

from kortex_core.db.types import (
    MemoryKind,
    MemoryLinkType,
    MemorySource,
    MemoryTier,
    ScopeType,
    Sensitivity,
)
from kortex_core.models.memory import Memory
from kortex_core.repositories.memory_repo import ScopeFilter
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService

from kortex_mcp.context import tool_context
from kortex_mcp.tools.base import ToolDef


def _memory_out(m: Memory) -> dict[str, Any]:
    """Wire format for a memory row — mirrors ``MemoryOut`` in kortex-api."""
    return {
        "public_id": str(m.public_id),
        "scope_type": m.scope_type,
        "scope_id": m.scope_id,
        "title": m.title,
        "body": m.body,
        "kind": m.kind,
        "sensitivity": m.sensitivity,
        "tier": m.tier,
        "importance": m.importance,
        "pinned": m.pinned,
        "access_count": m.access_count,
        "decay_score": m.decay_score,
        "created_at": m.created_at,
        "updated_at": m.updated_at,
        "last_accessed_at": m.last_accessed_at,
        "expires_at": m.expires_at,
        "metadata": m.metadata_,
    }


def _scope_props() -> dict[str, Any]:
    return {
        "scope_type": {
            "type": "string",
            "enum": [s.value for s in ScopeType],
            "description": "Scope kind the memory lives in.",
        },
        "scope_id": {
            "type": "integer",
            "description": "Numeric ID of the scope (workspace/project/session/org).",
        },
    }


# ---------- remember ----------


async def _remember(args: dict[str, Any]) -> dict[str, Any]:
    async with tool_context() as (session, principal):
        svc = MemoryService(session, principal)
        result = await svc.write(
            CreateMemoryInput(
                scope_type=ScopeType(args["scope_type"]),
                scope_id=int(args["scope_id"]),
                body=args["body"],
                title=args.get("title", ""),
                kind=MemoryKind(args.get("kind", MemoryKind.FACT.value)),
                sensitivity=Sensitivity(args.get("sensitivity", Sensitivity.INTERNAL.value)),
                source_type=MemorySource(args.get("source_type", MemorySource.MANUAL.value)),
                source_ref=args.get("source_ref"),
                importance=float(args.get("importance", 0.5)),
                pinned=bool(args.get("pinned", False)),
                metadata=args.get("metadata"),
            ),
            embed_inline=bool(args.get("embed_inline", False)),
            force=bool(args.get("force", False)),
        )
        return {**_memory_out(result.memory), "deduped": result.deduped}


_REMEMBER = ToolDef(
    name="remember",
    description=(
        "Store a new atomic memory (fact, preference, decision, etc.) at a "
        "given scope. Writing the same content twice returns the existing "
        "memory with `deduped: true` instead of storing a copy. "
        "The memory is embedded asynchronously by the worker; pass "
        "embed_inline=true to embed during the call (slower, useful for tests)."
    ),
    input_schema={
        "type": "object",
        "required": ["scope_type", "scope_id", "body"],
        "properties": {
            **_scope_props(),
            "body": {"type": "string", "description": "Memory content."},
            "title": {"type": "string", "default": ""},
            "kind": {
                "type": "string",
                "enum": [k.value for k in MemoryKind],
                "default": MemoryKind.FACT.value,
            },
            "sensitivity": {
                "type": "string",
                "enum": [s.value for s in Sensitivity],
                "default": Sensitivity.INTERNAL.value,
            },
            "source_type": {
                "type": "string",
                "enum": [s.value for s in MemorySource],
                "default": MemorySource.MANUAL.value,
            },
            "source_ref": {"type": ["object", "null"], "default": None},
            "importance": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.5,
            },
            "pinned": {"type": "boolean", "default": False},
            "metadata": {"type": ["object", "null"], "default": None},
            "embed_inline": {"type": "boolean", "default": False},
            "force": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Store this memory even if an identical one already exists in "
                    "the same scope. Leave false unless you specifically want a "
                    "second copy: by default a repeat write folds into the "
                    "existing memory and returns it with `deduped: true`, which "
                    "keeps duplicates out of later recall results."
                ),
            },
        },
        "additionalProperties": False,
    },
    handler=_remember,
)


# ---------- get_memory ----------


async def _get_memory(args: dict[str, Any]) -> dict[str, Any] | None:
    async with tool_context() as (session, principal):
        svc = MemoryService(session, principal)
        memory = await svc.get(uuid.UUID(args["public_id"]))
        return _memory_out(memory) if memory else None


_GET = ToolDef(
    name="get_memory",
    description="Fetch one memory by its public UUID.",
    input_schema={
        "type": "object",
        "required": ["public_id"],
        "properties": {"public_id": {"type": "string", "format": "uuid"}},
        "additionalProperties": False,
    },
    handler=_get_memory,
)


# ---------- list_memories ----------


async def _list_memories(args: dict[str, Any]) -> list[dict[str, Any]]:
    async with tool_context() as (session, principal):
        svc = MemoryService(session, principal)
        scope = None
        if args.get("scope_type") and args.get("scope_id") is not None:
            scope = ScopeFilter(
                scope_type=ScopeType(args["scope_type"]),
                scope_id=int(args["scope_id"]),
            )
        memories = await svc.list_(
            scope=scope,
            tier=MemoryTier(args["tier"]) if args.get("tier") else None,
            kind=MemoryKind(args["kind"]) if args.get("kind") else None,
            limit=int(args.get("limit", 50)),
            offset=int(args.get("offset", 0)),
        )
        return [_memory_out(m) for m in memories]


_LIST = ToolDef(
    name="list_memories",
    description="List memories in a scope, optionally filtered by tier or kind.",
    input_schema={
        "type": "object",
        "properties": {
            "scope_type": {
                "type": ["string", "null"],
                "enum": [*[s.value for s in ScopeType], None],
                "default": None,
            },
            "scope_id": {"type": ["integer", "null"], "default": None},
            "tier": {
                "type": ["string", "null"],
                "enum": [*[t.value for t in MemoryTier], None],
                "default": None,
            },
            "kind": {
                "type": ["string", "null"],
                "enum": [*[k.value for k in MemoryKind], None],
                "default": None,
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 200,
                "default": 50,
            },
            "offset": {"type": "integer", "minimum": 0, "default": 0},
        },
        "additionalProperties": False,
    },
    handler=_list_memories,
)


# ---------- update_memory ----------


async def _update_memory(args: dict[str, Any]) -> dict[str, Any] | None:
    async with tool_context() as (session, principal):
        svc = MemoryService(session, principal)
        memory = await svc.update(
            uuid.UUID(args["public_id"]),
            title=args.get("title"),
            body=args.get("body"),
            kind=MemoryKind(args["kind"]) if args.get("kind") else None,
            sensitivity=(Sensitivity(args["sensitivity"]) if args.get("sensitivity") else None),
            importance=args.get("importance"),
            metadata=args.get("metadata"),
        )
        return _memory_out(memory) if memory else None


_UPDATE = ToolDef(
    name="update_memory",
    description=(
        "Update a memory's title/body/kind/sensitivity/importance/metadata. "
        "Mutating the body clears the stored embedding so the worker re-embeds it."
    ),
    input_schema={
        "type": "object",
        "required": ["public_id"],
        "properties": {
            "public_id": {"type": "string", "format": "uuid"},
            "title": {"type": ["string", "null"], "default": None},
            "body": {"type": ["string", "null"], "default": None},
            "kind": {
                "type": ["string", "null"],
                "enum": [*[k.value for k in MemoryKind], None],
                "default": None,
            },
            "sensitivity": {
                "type": ["string", "null"],
                "enum": [*[s.value for s in Sensitivity], None],
                "default": None,
            },
            "importance": {
                "type": ["number", "null"],
                "minimum": 0.0,
                "maximum": 1.0,
                "default": None,
            },
            "metadata": {"type": ["object", "null"], "default": None},
        },
        "additionalProperties": False,
    },
    handler=_update_memory,
)


# ---------- delete_memory ----------


async def _delete_memory(args: dict[str, Any]) -> dict[str, Any]:
    async with tool_context() as (session, principal):
        svc = MemoryService(session, principal)
        ok = await svc.delete(uuid.UUID(args["public_id"]))
        return {"deleted": ok}


_DELETE = ToolDef(
    name="delete_memory",
    description="Soft-delete a memory by public UUID.",
    input_schema={
        "type": "object",
        "required": ["public_id"],
        "properties": {"public_id": {"type": "string", "format": "uuid"}},
        "additionalProperties": False,
    },
    handler=_delete_memory,
)


# ---------- pin_memory ----------


async def _pin_memory(args: dict[str, Any]) -> dict[str, Any] | None:
    async with tool_context() as (session, principal):
        svc = MemoryService(session, principal)
        memory = await svc.set_pinned(uuid.UUID(args["public_id"]), bool(args.get("pinned", True)))
        return _memory_out(memory) if memory else None


_PIN = ToolDef(
    name="pin_memory",
    description=(
        "Pin (default) or unpin a memory. Pinned memories bypass decay and get "
        "an absolute score floor in hybrid retrieval."
    ),
    input_schema={
        "type": "object",
        "required": ["public_id"],
        "properties": {
            "public_id": {"type": "string", "format": "uuid"},
            "pinned": {"type": "boolean", "default": True},
        },
        "additionalProperties": False,
    },
    handler=_pin_memory,
)


# ---------- link_memories ----------


async def _link_memories(args: dict[str, Any]) -> dict[str, Any]:
    async with tool_context() as (session, principal):
        svc = MemoryService(session, principal)
        link = await svc.link(
            from_public_id=uuid.UUID(args["from_public_id"]),
            to_public_id=uuid.UUID(args["to_public_id"]),
            link_type=MemoryLinkType(args.get("link_type", MemoryLinkType.RELATED.value)),
            weight=float(args.get("weight", 1.0)),
        )
        return {
            "linked": link is not None,
            "link_type": link.link_type if link else None,
            "weight": link.weight if link else None,
        }


_LINK = ToolDef(
    name="link_memories",
    description=(
        "Create a typed edge between two memories "
        "(related/derived_from/supersedes/contradicts/part_of)."
    ),
    input_schema={
        "type": "object",
        "required": ["from_public_id", "to_public_id"],
        "properties": {
            "from_public_id": {"type": "string", "format": "uuid"},
            "to_public_id": {"type": "string", "format": "uuid"},
            "link_type": {
                "type": "string",
                "enum": [lt.value for lt in MemoryLinkType],
                "default": MemoryLinkType.RELATED.value,
            },
            "weight": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 10.0,
                "default": 1.0,
            },
        },
        "additionalProperties": False,
    },
    handler=_link_memories,
)


TOOLS: list[ToolDef] = [_REMEMBER, _GET, _LIST, _UPDATE, _DELETE, _PIN, _LINK]
