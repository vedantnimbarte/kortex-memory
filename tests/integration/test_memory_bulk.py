"""Integration: MemoryService.bulk_apply pins/deletes many at once, under RBAC."""

from __future__ import annotations

import uuid

import pytest
from kortex_core.db.types import ScopeType
from kortex_core.services.auth_service import AuthService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.signup_service import SignupService

pytestmark = pytest.mark.integration


async def _owner_principal(session, email: str, org: str):  # type: ignore[no-untyped-def]
    result = await SignupService(session).register(
        email=email, password="hunter2pass", org_name=org
    )
    return (await AuthService(session).principal_from_jwt(result.access_token)).principal


async def test_bulk_pin_then_delete(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner_principal(session, "bulk@acme.io", "Bulk Co")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)

    ids = []
    for i in range(3):
        # Distinct bodies: identical content would dedup into a single row.
        m = await svc.create(
            CreateMemoryInput(scope_type=ScopeType.WORKSPACE, scope_id=ws.id, body=f"b{i}")
        )
        ids.append(m.public_id)

    assert await svc.bulk_apply("pin", ids) == 3
    for pid in ids:
        m = await svc.get(pid)
        assert m is not None and m.pinned is True

    # Unknown ids are skipped, not fatal.
    assert await svc.bulk_apply("unpin", [ids[0], uuid.uuid4()]) == 1

    assert await svc.bulk_apply("delete", ids) == 3
    for pid in ids:
        assert await svc.get(pid) is None


async def test_bulk_unknown_action_rejected(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner_principal(session, "bulk2@acme.io", "Bulk Co 2")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    m = await svc.create(
        CreateMemoryInput(scope_type=ScopeType.WORKSPACE, scope_id=ws.id, body="b")
    )
    with pytest.raises(ValueError):
        await svc.bulk_apply("nuke", [m.public_id])
