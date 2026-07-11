"""Org repository (superuser-only mutations; reads scoped to principal.org_id)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from kortex_core.models.org import Org
from kortex_core.repositories.base import BaseRepository, TenantViolationError


class OrgRepository(BaseRepository[Org]):
    model = Org

    async def get_by_id(self, org_id: int) -> Org | None:
        principal = self.principal
        if not principal.is_superuser and org_id != principal.org_id:
            raise TenantViolationError(f"cannot read org {org_id}")
        stmt = select(Org).where(Org.id == org_id, Org.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Org | None:
        stmt = select(Org).where(Org.slug == slug, Org.deleted_at.is_(None))
        org = (await self._session.execute(stmt)).scalar_one_or_none()
        if org is None:
            return None
        principal = self.principal
        if not principal.is_superuser and org.id != principal.org_id:
            return None
        return org

    async def get_by_public_id(self, public_id: uuid.UUID) -> Org | None:
        stmt = select(Org).where(Org.public_id == public_id, Org.deleted_at.is_(None))
        org = (await self._session.execute(stmt)).scalar_one_or_none()
        if org is None:
            return None
        principal = self.principal
        if not principal.is_superuser and org.id != principal.org_id:
            return None
        return org

    async def get_by_stripe_customer(self, customer_id: str) -> Org | None:
        """Reverse-lookup by the Stripe customer id stored in settings.billing.
        Superuser-only — used by the webhook, which runs unauthenticated."""
        if not self.principal.is_superuser:
            raise TenantViolationError("stripe lookup is superuser-only")
        stmt = select(Org).where(
            Org.settings["billing"]["stripe_customer_id"].astext == customer_id,
            Org.deleted_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_principal(self) -> list[Org]:
        principal = self.principal
        if principal.is_superuser:
            stmt = select(Org).where(Org.deleted_at.is_(None)).order_by(Org.id)
        else:
            stmt = select(Org).where(Org.id == principal.org_id, Org.deleted_at.is_(None))
        return list((await self._session.execute(stmt)).scalars().all())

    async def create(self, *, slug: str, name: str, plan: str = "free") -> Org:
        if not self.principal.is_superuser:
            raise TenantViolationError("only superusers may create orgs")
        org = Org(slug=slug, name=name, plan=plan, settings={})
        self._session.add(org)
        await self._session.flush()
        return org
