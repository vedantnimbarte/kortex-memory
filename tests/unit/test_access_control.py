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
    assert not ac.can_read(principal, ResourceRef(scope=scope, sensitivity=Sensitivity.SECRET))
    assert ac.can_read(principal, ResourceRef(scope=scope, sensitivity=Sensitivity.INTERNAL))


def test_member_cannot_write_secret_but_can_write_confidential() -> None:
    scope = ScopeRef(type=ScopeType.PROJECT, id=1)
    principal = _principal(role=Role.MEMBER, scope=scope)
    ac = AccessControl()
    assert ac.can_write(principal, ResourceRef(scope=scope, sensitivity=Sensitivity.CONFIDENTIAL))
    assert not ac.can_write(principal, ResourceRef(scope=scope, sensitivity=Sensitivity.SECRET))


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
    assert not ac.can_read(principal, ResourceRef(scope=scope, sensitivity=Sensitivity.PUBLIC))
    assert not ac.can_admin(principal, scope)


def test_superuser_bypasses() -> None:
    scope = ScopeRef(type=ScopeType.PROJECT, id=1)
    principal = Principal(actor_id=1, actor_kind=ActorKind.USER, org_id=10, is_superuser=True)
    ac = AccessControl()
    assert ac.can_read(principal, ResourceRef(scope=scope, sensitivity=Sensitivity.SECRET))
    assert ac.can_admin(principal, scope)


def test_is_admin_anywhere() -> None:
    ac = AccessControl()
    org_a = ScopeRef(type=ScopeType.ORG, id=1)
    assert ac.is_admin_anywhere(_principal(role=Role.ADMIN, scope=org_a))
    assert ac.is_admin_anywhere(_principal(role=Role.OWNER, scope=org_a))
    assert not ac.is_admin_anywhere(_principal(role=Role.MEMBER, scope=org_a))
    assert not ac.is_admin_anywhere(_principal(role=None, scope=org_a))


def test_cannot_admin_a_scope_you_are_not_in() -> None:
    """The membership-grant takeover: an admin of org 1 must not be able to
    admin/own org 2 (a scope they hold no membership on)."""
    ac = AccessControl()
    org_1 = ScopeRef(type=ScopeType.ORG, id=1)
    org_2 = ScopeRef(type=ScopeType.ORG, id=2)
    admin_of_org1 = _principal(role=Role.ADMIN, scope=org_1)
    assert ac.can_admin(admin_of_org1, org_1)
    assert not ac.can_admin(admin_of_org1, org_2)
    assert not ac.can_own(admin_of_org1, org_2)
    # And an ADMIN cannot grant OWNER even on their own scope.
    assert not ac.can_own(admin_of_org1, org_1)
