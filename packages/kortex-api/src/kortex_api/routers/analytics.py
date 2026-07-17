"""Analytics router: org-/scope-wide memory aggregates for the dashboard.

Replaces the web console's former client-side approximation (which described
only a sampled page) with true totals computed in SQL.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query
from kortex_core.db.types import ScopeType
from kortex_core.repositories.memory_repo import ScopeFilter
from kortex_core.services.memory_service import MemoryService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.schemas.memory import AnalyticsOut, CountSlice, DecayHealth, MemoryOut

router = APIRouter(prefix="/v1/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsOut)
async def summary(
    principal: PrincipalDep,
    session: SessionDep,
    scope_type: ScopeType | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    days: int = Query(default=14, ge=1, le=90),
) -> AnalyticsOut:
    svc = MemoryService(session, principal)
    scope = (
        ScopeFilter(scope_type=scope_type, scope_id=scope_id)
        if scope_type and scope_id is not None
        else None
    )
    a = await svc.analytics(now=dt.datetime.now(tz=dt.UTC), scope=scope, days=days)
    return AnalyticsOut(
        count=a.count,
        pinned=a.pinned,
        avg_decay=a.avg_decay,
        total_access=a.total_access,
        by_tier=[CountSlice(label=k, value=v) for k, v in a.by_tier],
        by_kind=[CountSlice(label=k, value=v) for k, v in a.by_kind],
        by_sensitivity=[CountSlice(label=k, value=v) for k, v in a.by_sensitivity],
        decay_health=DecayHealth(
            healthy=a.decay_health[0], aging=a.decay_health[1], faded=a.decay_health[2]
        ),
        top_accessed=[MemoryOut.model_validate(m) for m in a.top_accessed],
        timeline=a.timeline,
    )
