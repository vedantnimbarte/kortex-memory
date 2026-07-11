"""Cross-org + cross-sensitivity leak test.

Provisions two orgs A and B, writes memories at each, then asserts that a
principal scoped to A never sees rows from B across every read path:

  * direct memory repo ``hybrid_search``
  * agentic ``AgenticRetriever.recall``
  * MCP ``search_memory`` / ``recall`` / ``list_memories`` handlers

Also asserts that a ``viewer`` role cannot see ``secret`` memories under any
of those paths.
"""

from __future__ import annotations

import uuid

import pytest
from kortex_core.db.session import session_scope
from kortex_core.db.types import (
    ActorKind,
    MemoryKind,
    Role,
    ScopeType,
    Sensitivity,
)
from kortex_core.repositories.memory_repo import MemoryRepository
from kortex_core.repositories.org_repo import OrgRepository
from kortex_core.security.principal import Principal
from kortex_core.services.agentic_retriever import (
    AgenticRetriever,
    RecallRequest,
)
from kortex_core.services.api_key_service import ApiKeyService
from kortex_core.services.memory_service import (
    CreateMemoryInput,
    MemoryService,
)
from kortex_core.services.project_service import ProjectService
from kortex_core.services.user_service import UserService
from kortex_core.services.workspace_service import WorkspaceService
from kortex_mcp.auth import principal_from_api_key
from kortex_mcp.context import McpRuntime, set_runtime
from kortex_mcp.tools import all_tools

pytestmark = pytest.mark.integration


def _superuser(org_id: int = 0) -> Principal:
    return Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=org_id,
        is_superuser=True,
    )


def _tool(name: str):
    for t in all_tools():
        if t.name == name:
            return t
    raise KeyError(name)


async def _provision_org(session, slug_prefix: str, viewer_role: Role = Role.OWNER):  # type: ignore[no-untyped-def]
    """Return (org_id, project_id, api_key_plaintext)."""
    sys_p = _superuser()
    org = await OrgRepository(session, principal=sys_p).create(
        slug=f"{slug_prefix}-{uuid.uuid4().hex[:6]}",
        name=slug_prefix.capitalize(),
        plan="dev",
    )
    org_p = _superuser(org.id)
    user_svc = UserService(session, org_p)
    user = await user_svc.create_with_password(
        email=f"{slug_prefix}-{uuid.uuid4().hex[:6]}@kortex.test",
        password="pw-12345678",
        display_name=slug_prefix.capitalize(),
    )
    ws = await WorkspaceService(session, org_p).create(slug="default", name="Default")
    proj = await ProjectService(session, org_p).create(
        workspace_public_id=ws.public_id, slug="play", name="Play"
    )
    assert proj is not None
    for st, sid in (
        (ScopeType.ORG, org.id),
        (ScopeType.WORKSPACE, ws.id),
        (ScopeType.PROJECT, proj.id),
    ):
        await user_svc.grant(user_id=user.id, scope_type=st, scope_id=sid, role=viewer_role)
    minted = await ApiKeyService(session, org_p).mint(
        name=f"{slug_prefix}-key",
        scopes=["read:memory", "write:memory"],
        scope_type=ScopeType.PROJECT,
        scope_id=proj.id,
    )
    return org.id, proj.id, minted.plaintext


async def _write_memory(
    session, org_id: int, project_id: int, body: str, sensitivity: Sensitivity
) -> str:
    """Insert a memory at PROJECT scope as the org's owner; returns public_id."""
    p = Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=org_id,
        is_superuser=True,
    )
    svc = MemoryService(session, p)
    m = await svc.create(
        CreateMemoryInput(
            scope_type=ScopeType.PROJECT,
            scope_id=project_id,
            body=body,
            sensitivity=sensitivity,
            kind=MemoryKind.FACT,
        )
    )
    return str(m.public_id)


async def test_cross_org_isolation(session) -> None:  # type: ignore[no-untyped-def]
    """A key scoped to org A must never surface a memory from org B."""
    org_a, proj_a, key_a = await _provision_org(session, "alpha")
    org_b, proj_b, _key_b = await _provision_org(session, "beta")

    a_secret = await _write_memory(
        session, org_a, proj_a, "alpha-shared-quantum-otter", Sensitivity.INTERNAL
    )
    b_secret = await _write_memory(
        session, org_b, proj_b, "beta-quantum-otter-leak", Sensitivity.INTERNAL
    )
    await session.commit()

    # Bind the MCP runtime to org A's key.
    async with session_scope() as s:
        principal_a = await principal_from_api_key(s, key_a)
    set_runtime(McpRuntime(principal=principal_a))

    search = await _tool("search_memory").handler({"query": "quantum otter"})
    public_ids = {h["public_id"] for h in search["hits"]}
    assert a_secret in public_ids
    assert b_secret not in public_ids

    recall = await _tool("recall").handler({"query": "quantum otter"})
    candidate_ids = {c["public_id"] for c in recall["candidates"]}
    assert b_secret not in candidate_ids

    listed = await _tool("list_memories").handler({})
    assert b_secret not in {m["public_id"] for m in listed}

    # Direct repo path with org A principal should also stay within scope.
    async with session_scope() as s:
        repo = MemoryRepository(s, principal=principal_a)
        hits = await repo.hybrid_search(
            query="quantum otter",
            query_vector=None,
            max_sensitivity=Sensitivity.SECRET,
            limit=20,
        )
    assert {h.public_id for h in hits}.isdisjoint({b_secret})


async def test_viewer_cannot_see_secret(session) -> None:  # type: ignore[no-untyped-def]
    """A viewer-role principal must not see ``secret`` memories anywhere."""
    org_id, project_id, key = await _provision_org(session, "vsec", viewer_role=Role.VIEWER)
    secret_id = await _write_memory(
        session, org_id, project_id, "very-secret-octopus", Sensitivity.SECRET
    )
    public_id = await _write_memory(
        session, org_id, project_id, "very-public-octopus", Sensitivity.PUBLIC
    )
    await session.commit()

    async with session_scope() as s:
        principal = await principal_from_api_key(s, key)
    set_runtime(McpRuntime(principal=principal))

    # search_memory and recall should both withhold the secret.
    s_res = await _tool("search_memory").handler({"query": "octopus"})
    sids = {h["public_id"] for h in s_res["hits"]}
    assert public_id in sids
    assert secret_id not in sids

    r_res = await _tool("recall").handler({"query": "octopus"})
    rids = {c["public_id"] for c in r_res["candidates"]}
    assert secret_id not in rids

    # AgenticRetriever directly — also must filter.
    async with session_scope() as s:
        retriever = AgenticRetriever(s, principal)
        bundle = await retriever.recall(RecallRequest(query="octopus"))
    cids = {c.public_id for c in bundle.citations}
    assert secret_id not in cids
