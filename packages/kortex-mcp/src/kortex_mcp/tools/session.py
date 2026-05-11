"""Session tools: start_session, end_session, list_sessions."""

from __future__ import annotations

import uuid
from typing import Any

from kortex_core.db.types import AgentKind
from kortex_core.models.session import Session
from kortex_core.services.session_service import SessionService

from kortex_mcp.context import tool_context
from kortex_mcp.tools.base import ToolDef


def _session_out(s: Session) -> dict[str, Any]:
    return {
        "public_id": str(s.public_id),
        "agent_kind": s.agent_kind,
        "title": s.title,
        "client_metadata": s.client_metadata,
        "started_at": s.started_at,
        "ended_at": s.ended_at,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


# ---------- start_session ----------


async def _start_session(args: dict[str, Any]) -> dict[str, Any] | None:
    async with tool_context() as (session, principal):
        svc = SessionService(session, principal)
        created = await svc.start(
            project_public_id=uuid.UUID(args["project_public_id"]),
            agent_kind=AgentKind(args.get("agent_kind", AgentKind.OTHER.value)),
            title=args.get("title", ""),
            client_metadata=args.get("client_metadata") or {},
        )
        return _session_out(created) if created else None


_START = ToolDef(
    name="start_session",
    description=(
        "Begin a new agent session bound to a project. Returns the public_id "
        "to use with subsequent message ingestion and memory creation."
    ),
    input_schema={
        "type": "object",
        "required": ["project_public_id"],
        "properties": {
            "project_public_id": {"type": "string", "format": "uuid"},
            "agent_kind": {
                "type": "string",
                "enum": [a.value for a in AgentKind],
                "default": AgentKind.OTHER.value,
            },
            "title": {"type": "string", "default": ""},
            "client_metadata": {"type": ["object", "null"], "default": None},
        },
        "additionalProperties": False,
    },
    handler=_start_session,
)


# ---------- end_session ----------


async def _end_session(args: dict[str, Any]) -> dict[str, Any] | None:
    async with tool_context() as (session, principal):
        svc = SessionService(session, principal)
        ended = await svc.end(uuid.UUID(args["public_id"]))
        return _session_out(ended) if ended else None


_END = ToolDef(
    name="end_session",
    description="Mark a session as ended (sets ended_at).",
    input_schema={
        "type": "object",
        "required": ["public_id"],
        "properties": {"public_id": {"type": "string", "format": "uuid"}},
        "additionalProperties": False,
    },
    handler=_end_session,
)


# ---------- list_sessions ----------


async def _list_sessions(args: dict[str, Any]) -> list[dict[str, Any]]:
    async with tool_context() as (session, principal):
        svc = SessionService(session, principal)
        sessions = await svc.list_for_project(
            uuid.UUID(args["project_public_id"]),
            limit=int(args.get("limit", 50)),
        )
        return [_session_out(s) for s in sessions]


_LIST = ToolDef(
    name="list_sessions",
    description="List sessions in a project, newest first.",
    input_schema={
        "type": "object",
        "required": ["project_public_id"],
        "properties": {
            "project_public_id": {"type": "string", "format": "uuid"},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 200,
                "default": 50,
            },
        },
        "additionalProperties": False,
    },
    handler=_list_sessions,
)


TOOLS: list[ToolDef] = [_START, _END, _LIST]
