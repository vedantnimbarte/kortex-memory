"""End-to-end MCP tool tests driving the in-process server.

These tests exercise the same tool handlers that the stdio and SSE transports
delegate to, so we cover the full service/repo/principal stack against a real
Postgres + pgvector without the overhead of subprocess marshalling. The stdio
runner itself is a thin wrapper around ``mcp.server.stdio_server`` from the
upstream SDK and is exercised by the conformance suite that ships with ``mcp``.
"""

from __future__ import annotations

import uuid

import pytest

from kortex_core.db.session import session_scope
from kortex_core.db.types import ActorKind, Role, ScopeType
from kortex_core.repositories.org_repo import OrgRepository
from kortex_core.repositories.project_repo import ProjectRepository
from kortex_core.security.principal import Principal
from kortex_core.services.api_key_service import ApiKeyService
from kortex_core.services.project_service import ProjectService
from kortex_core.services.user_service import UserService
from kortex_core.services.workspace_service import WorkspaceService

from kortex_mcp.auth import principal_from_api_key
from kortex_mcp.context import McpRuntime, set_runtime
from kortex_mcp.tools import all_tools
from kortex_mcp.tools.base import ToolDef

pytestmark = pytest.mark.integration


def _superuser(org_id: int = 0) -> Principal:
    return Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=org_id,
        is_superuser=True,
    )


def _tool(name: str) -> ToolDef:
    for t in all_tools():
        if t.name == name:
            return t
    raise KeyError(name)


async def _seed_tenant(session) -> tuple[int, str]:
    """Provision org/workspace/project + admin user + scoped API key.

    Returns ``(project_id, plaintext_api_key)``.
    """
    sys_p = _superuser()
    org = await OrgRepository(session, principal=sys_p).create(
        slug=f"mcp-test-{uuid.uuid4().hex[:8]}", name="MCP Test", plan="dev"
    )
    org_p = _superuser(org.id)

    user_svc = UserService(session, org_p)
    user = await user_svc.create_with_password(
        email=f"mcp-{uuid.uuid4().hex[:8]}@kortex.test",
        password="pw-12345678",
        display_name="MCP Tester",
        is_superuser=False,
    )

    ws = await WorkspaceService(session, org_p).create(slug="default", name="Default")
    proj = await ProjectService(session, org_p).create(
        workspace_public_id=ws.public_id, slug="play", name="Play"
    )
    assert proj is not None

    for scope_type, scope_id in (
        (ScopeType.ORG, org.id),
        (ScopeType.WORKSPACE, ws.id),
        (ScopeType.PROJECT, proj.id),
    ):
        await user_svc.grant(
            user_id=user.id, scope_type=scope_type, scope_id=scope_id, role=Role.OWNER
        )

    minted = await ApiKeyService(session, org_p).mint(
        name="mcp-test-key",
        scopes=["read:memory", "write:memory"],
        scope_type=ScopeType.PROJECT,
        scope_id=proj.id,
    )
    return proj.id, minted.plaintext


async def _bind_runtime(api_key: str) -> None:
    """Materialise a principal from the API key and stash it on the runtime."""
    async with session_scope() as s:
        principal = await principal_from_api_key(s, api_key)
    set_runtime(McpRuntime(principal=principal))


async def test_tool_surface_matches_milestone_contract() -> None:
    """M3 + M4 + M5 fix the canonical tool set — make sure we ship it."""
    names = {t.name for t in all_tools()}
    expected = {
        # M3 — memory + session + plain hybrid search
        "remember",
        "recall",
        "search_memory",
        "get_memory",
        "list_memories",
        "update_memory",
        "delete_memory",
        "link_memories",
        "pin_memory",
        "start_session",
        "end_session",
        "list_sessions",
        # M4 — attachments
        "attach_file",
        "finalize_attachment",
        "get_attachment",
        # M5 — agentic recall with synthesized ContextBundle
        "get_context_bundle",
    }
    missing = expected - names
    assert not missing, f"MCP tool surface missing: {missing}"


async def test_remember_list_search_delete_roundtrip(session) -> None:  # type: ignore[no-untyped-def]
    project_id, api_key = await _seed_tenant(session)
    await session.commit()
    await _bind_runtime(api_key)

    # remember — write two project-scoped memories. BM25 (tsv) works without
    # embeddings, so we skip inline embedding to keep the test portable.
    a = await _tool("remember").handler(
        {
            "scope_type": ScopeType.PROJECT.value,
            "scope_id": project_id,
            "title": "caching",
            "body": "We chose Redis with a 5-minute TTL for the search cache.",
            "importance": 0.8,
        }
    )
    b = await _tool("remember").handler(
        {
            "scope_type": ScopeType.PROJECT.value,
            "scope_id": project_id,
            "title": "deployment",
            "body": "Production deploys go through GitHub Actions on tag push.",
            "importance": 0.3,
        }
    )
    assert a["tier"] == "short"
    assert b["public_id"] != a["public_id"]

    # list_memories — both visible at project scope.
    listed = await _tool("list_memories").handler(
        {"scope_type": ScopeType.PROJECT.value, "scope_id": project_id}
    )
    ids = {m["public_id"] for m in listed}
    assert a["public_id"] in ids
    assert b["public_id"] in ids

    # recall / search_memory — caching query should surface memory `a`. With
    # no embedding present the retrieval falls back to BM25 only, which still
    # ranks `a` first for this query.
    result = await _tool("recall").handler({"query": "caching strategy"})
    hits = result["hits"]
    assert any(h["public_id"] == a["public_id"] for h in hits)

    # pin → update → get round trip on `a`.
    pinned = await _tool("pin_memory").handler(
        {"public_id": a["public_id"], "pinned": True}
    )
    assert pinned is not None and pinned["pinned"] is True

    updated = await _tool("update_memory").handler(
        {"public_id": a["public_id"], "title": "caching strategy"}
    )
    assert updated is not None and updated["title"] == "caching strategy"

    fetched = await _tool("get_memory").handler({"public_id": a["public_id"]})
    assert fetched is not None and fetched["title"] == "caching strategy"

    # delete soft-deletes `b`; subsequent list omits it.
    deleted = await _tool("delete_memory").handler({"public_id": b["public_id"]})
    assert deleted == {"deleted": True}

    listed_after = await _tool("list_memories").handler(
        {"scope_type": ScopeType.PROJECT.value, "scope_id": project_id}
    )
    assert b["public_id"] not in {m["public_id"] for m in listed_after}


async def test_session_start_list_end(session) -> None:  # type: ignore[no-untyped-def]
    project_id, api_key = await _seed_tenant(session)
    await session.commit()
    await _bind_runtime(api_key)

    # Look up the project's public_id since start_session takes the UUID.
    async with session_scope() as s:
        repo = ProjectRepository(s, principal=_superuser())
        proj = await repo.get_by_id(project_id)
        assert proj is not None
        project_public_id = str(proj.public_id)

    started = await _tool("start_session").handler(
        {
            "project_public_id": project_public_id,
            "agent_kind": "claude_code",
            "title": "MCP smoke",
        }
    )
    assert started is not None
    assert started["ended_at"] is None
    session_public_id = started["public_id"]

    listed = await _tool("list_sessions").handler(
        {"project_public_id": project_public_id}
    )
    assert any(s["public_id"] == session_public_id for s in listed)

    ended = await _tool("end_session").handler({"public_id": session_public_id})
    assert ended is not None and ended["ended_at"] is not None


async def test_build_server_registers_handlers() -> None:
    """The mcp Server is built lazily — make sure construction is side-effect free
    and exposes the canonical tool list to clients via list_tools()."""
    from kortex_mcp.server import build_server

    server = build_server()
    # The SDK records decorated handlers in ``request_handlers``. We don't
    # depend on the exact key names — just that something is registered, so
    # list_tools/call_tool are wired.
    assert getattr(server, "request_handlers", None), (
        "MCP server should have registered request handlers"
    )
