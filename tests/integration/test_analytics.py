"""Integration: MemoryService.analytics aggregates the full live set in SQL."""

from __future__ import annotations

import datetime as dt

import pytest
from kortex_core.db.types import MemoryKind, ScopeType
from kortex_core.services.auth_service import AuthService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.signup_service import SignupService

pytestmark = pytest.mark.integration

NOW = dt.datetime(2026, 1, 15, 12, 0, tzinfo=dt.UTC)


async def _owner_principal(session, email: str, org: str):  # type: ignore[no-untyped-def]
    result = await SignupService(session).register(
        email=email, password="hunter2pass", org_name=org
    )
    return (await AuthService(session).principal_from_jwt(result.access_token)).principal


async def test_analytics_aggregates_full_set(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner_principal(session, "an@acme.io", "Analytics Co")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)

    async def make(**over) -> None:  # type: ignore[no-untyped-def]
        m = await svc.create(
            CreateMemoryInput(scope_type=ScopeType.WORKSPACE, scope_id=ws.id, body="b")
        )
        for k, v in over.items():
            setattr(m, k, v)
        await session.flush()

    # 4 memories: varied tier / kind / decay / access / pin / created_at.
    #
    # `created_at` is pinned relative to NOW on every row. Leaving it to the
    # server default meant "today" was the wall clock while the assertions
    # measured a 14-day window ending at a hard-coded NOW — so this test passed
    # only while real time happened to sit near that date, and started failing
    # the moment it did not.
    await make(
        tier="long",
        kind=MemoryKind.DECISION.value,
        decay_score=0.9,
        access_count=10,
        pinned=True,
        created_at=NOW,
    )
    await make(
        tier="long",
        kind=MemoryKind.FACT.value,
        decay_score=0.5,
        access_count=3,
        created_at=NOW,
    )
    await make(
        tier="short",
        kind=MemoryKind.FACT.value,
        decay_score=0.1,
        access_count=1,
        created_at=NOW,
    )
    await make(
        tier="mid",
        kind=MemoryKind.FACT.value,
        decay_score=0.5,
        created_at=NOW - dt.timedelta(days=5),
    )

    a = await svc.analytics(now=NOW, scope=None, days=14)

    assert a.count == 4
    assert a.pinned == 1
    assert a.total_access == 14
    assert abs(a.avg_decay - (0.9 + 0.5 + 0.1 + 0.5) / 4) < 1e-9

    assert dict(a.by_tier) == {"long": 2, "short": 1, "mid": 1}
    assert dict(a.by_kind) == {"decision": 1, "fact": 3}

    # decay buckets: 0.9 healthy; 0.5,0.5 aging; 0.1 faded.
    assert a.decay_health == (1, 2, 1)

    # top_accessed ordered desc.
    assert a.top_accessed[0].access_count == 10

    # timeline: len 14, 3 created "today" (last bucket), 1 five days ago.
    assert len(a.timeline) == 14
    assert a.timeline[13] == 3
    assert a.timeline[8] == 1


async def test_analytics_scope_filter(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner_principal(session, "an2@acme.io", "Analytics Co 2")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    await svc.create(CreateMemoryInput(scope_type=ScopeType.WORKSPACE, scope_id=ws.id, body="in"))
    await svc.create(
        CreateMemoryInput(scope_type=ScopeType.ORG, scope_id=principal.org_id, body="out")
    )

    from kortex_core.repositories.memory_repo import ScopeFilter

    scoped = await svc.analytics(
        now=NOW, scope=ScopeFilter(scope_type=ScopeType.WORKSPACE, scope_id=ws.id)
    )
    assert scoped.count == 1
