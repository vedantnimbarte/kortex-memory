"""Integration smoke test: superuser can create an org and read it back."""

from __future__ import annotations

import pytest

from kortex_core.db.types import ActorKind
from kortex_core.repositories.org_repo import OrgRepository
from kortex_core.security.principal import Principal

pytestmark = pytest.mark.integration


async def test_create_and_read_org(session) -> None:  # type: ignore[no-untyped-def]
    super_p = Principal(
        actor_id=0, actor_kind=ActorKind.SYSTEM, org_id=0, is_superuser=True
    )
    repo = OrgRepository(session, principal=super_p)
    org = await repo.create(slug="acme-test", name="Acme Test")
    assert org.id > 0
    fetched = await repo.get_by_slug("acme-test")
    assert fetched is not None
    assert fetched.id == org.id
