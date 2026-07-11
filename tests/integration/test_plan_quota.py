"""Integration: plan caps block resource creation past the limit."""

from __future__ import annotations

import pytest
from kortex_core.db.types import ScopeType
from kortex_core.security import plan_limits
from kortex_core.security.plan_limits import PlanLimits, QuotaExceededError
from kortex_core.services.auth_service import AuthService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.signup_service import SignupService
from kortex_core.services.workspace_service import WorkspaceService

pytestmark = pytest.mark.integration


async def _owner_principal(session, email: str, org: str):  # type: ignore[no-untyped-def]
    result = await SignupService(session).register(
        email=email, password="hunter2pass", org_name=org
    )
    return (await AuthService(session).principal_from_jwt(result.access_token)).principal


async def test_free_plan_blocks_memories_over_cap(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Shrink the free cap so the test stays cheap.
    monkeypatch.setitem(
        plan_limits.PLAN_LIMITS, "free", PlanLimits(max_memories=2, max_workspaces=1)
    )
    principal = await _owner_principal(session, "quota@acme.io", "Quota Co")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)

    svc = MemoryService(session, principal)
    payload = CreateMemoryInput(scope_type=ScopeType.WORKSPACE, scope_id=ws.id, body="m")
    await svc.create(payload)
    await svc.create(payload)  # at cap (2)
    with pytest.raises(QuotaExceededError):
        await svc.create(payload)  # 3rd exceeds


async def test_free_plan_blocks_second_workspace(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setitem(
        plan_limits.PLAN_LIMITS, "free", PlanLimits(max_memories=1_000, max_workspaces=1)
    )
    principal = await _owner_principal(session, "ws@acme.io", "WS Co")
    # Signup already created the one allowed workspace.
    with pytest.raises(QuotaExceededError):
        await WorkspaceService(session, principal).create(slug="second", name="Second")
