"""Unit tests for the access control policy."""

from __future__ import annotations

import pytest

from kortex_core.db.types import ActorKind, Role, ScopeType, Sensitivity
from kortex_core.security.principal import Principal, ScopeRef
from kortex_core.services.access_control import AccessControl, ResourceRef

pytestmark = pytest.mark.unit


def _principal(*, role: Role | None, scope: ScopeRef) -> Principal:
    roles = {scope: role} if role is not None else {}
    return Principal(
        actor_id=1,
        actor_kind=ActorKind.USER,
        org_id=10,
        roles=roles,
    )


def test_viewer_cannot_read_secret() -> None:
    scope = ScopeRef(type=ScopeType.PROJECT, id=1)
    principal = _principal(role=Role.VIEWER, scope=scope)
    ac = AccessControl()
    assert not ac.can_read(
        principal, ResourceRef(scope=scope, sensitivity=Sensitivity.SECRET)
    )
    assert ac.can_read(
        principal, ResourceRef(scope=scope, sensitivity=Sensitivity.INTERNAL)
    )


def test_member_cannot_write_secret_but_can_write_confidential() -> None:
    scope = ScopeRef(type=ScopeType.PROJECT, id=1)
    principal = _principal(role=Role.MEMBER, scope=scope)
    ac = AccessControl()
    assert ac.can_write(
        principal, ResourceRef(scope=scope, sensitivity=Sensitivity.CONFIDENTIAL)
    )
    assert not ac.can_write(
        principal, ResourceRef(scope=scope, sensitivity=Sensitivity.SECRET)
    )


def test_owner_can_admin() -> None:
    scope = ScopeRef(type=ScopeType.PROJECT, id=1)
    principal = _principal(role=Role.OWNER, scope=scope)
    ac = AccessControl()
    assert ac.can_admin(principal, scope)
    assert ac.can_own(principal, scope)


def test_no_role_means_no_access() -> None:
    scope = ScopeRef(type=ScopeType.PROJECT, id=1)
    principal = _principal(role=None, scope=scope)
    ac = AccessControl()
    assert not ac.can_read(
        principal, ResourceRef(scope=scope, sensitivity=Sensitivity.PUBLIC)
    )
    assert not ac.can_admin(principal, scope)


def test_superuser_bypasses() -> None:
    scope = ScopeRef(type=ScopeType.PROJECT, id=1)
    principal = Principal(
        actor_id=1, actor_kind=ActorKind.USER, org_id=10, is_superuser=True
    )
    ac = AccessControl()
    assert ac.can_read(
        principal, ResourceRef(scope=scope, sensitivity=Sensitivity.SECRET)
    )
    assert ac.can_admin(principal, scope)
