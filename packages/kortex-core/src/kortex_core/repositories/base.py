"""Base repository.

Enforces tenancy: every query goes through :meth:`tenant_query`, which adds the
``org_id`` filter (or asserts superuser). The CI lint rule under
``tools/ruff_plugins/tenant_check.py`` blocks raw ``select(Model)`` calls inside
this package's ``repositories/`` to keep this chokepoint honest.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.base import Base
from kortex_core.security.principal import Principal, require_principal

ModelT = TypeVar("ModelT", bound=Base)


class TenantViolationError(PermissionError):
    """Raised when a query attempts to escape tenant isolation."""


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession, *, principal: Principal | None = None):
        self._session = session
        self._principal = principal

    @property
    def session(self) -> AsyncSession:
        return self._session

    @property
    def principal(self) -> Principal:
        return self._principal or require_principal()

    def tenant_query(self, *cols: Any) -> Select[Any]:
        """Build a SELECT pre-filtered to the principal's org. Use this everywhere.

        - For models with an ``org_id`` column, scope to ``principal.org_id``.
        - Superuser principals bypass the filter (audited).
        """
        targets = cols if cols else (self.model,)
        stmt = select(*targets)
        principal = self.principal
        if principal.is_superuser:
            return stmt
        if hasattr(self.model, "org_id"):
            stmt = stmt.where(self.model.org_id == principal.org_id)  # type: ignore[attr-defined]
        return stmt

    def assert_same_org(self, org_id: int) -> None:
        """Reject cross-org operations attempted by non-superusers."""
        principal = self.principal
        if principal.is_superuser:
            return
        if org_id != principal.org_id:
            raise TenantViolationError(
                f"principal org={principal.org_id} cannot access org={org_id}"
            )

    async def add(self, obj: ModelT) -> ModelT:
        if hasattr(obj, "org_id") and not self.principal.is_superuser:
            self.assert_same_org(obj.org_id)  # type: ignore[attr-defined]
        self._session.add(obj)
        await self._session.flush()
        return obj
