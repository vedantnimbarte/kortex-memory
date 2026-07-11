"""Centralized authorization checks.

This module is the single chokepoint for "may principal X do action Y on
resource Z?" decisions. The default policy combines RBAC role × sensitivity tier
per the plan §J. The :class:`RoleSensitivityPolicy` skill in
``kortex_core.skills.access_policy`` is the pluggable strategy; this service
delegates to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from kortex_core.db.types import Role, ScopeType, Sensitivity
from kortex_core.security.principal import Principal, ScopeRef


class AccessDeniedError(PermissionError):
    """Raised when an action is denied by policy."""


_ROLE_RANK: Final[dict[Role, int]] = {
    Role.VIEWER: 1,
    Role.MEMBER: 2,
    Role.ADMIN: 3,
    Role.OWNER: 4,
}


_SENSITIVITY_RANK: Final[dict[Sensitivity, int]] = {
    Sensitivity.PUBLIC: 1,
    Sensitivity.INTERNAL: 2,
    Sensitivity.CONFIDENTIAL: 3,
    Sensitivity.SECRET: 4,
}


# Maximum sensitivity readable per role.
_READ_SENSITIVITY_BY_ROLE: Final[dict[Role, Sensitivity]] = {
    Role.VIEWER: Sensitivity.CONFIDENTIAL,
    Role.MEMBER: Sensitivity.CONFIDENTIAL,
    Role.ADMIN: Sensitivity.SECRET,
    Role.OWNER: Sensitivity.SECRET,
}


# Maximum sensitivity writeable per role.
_WRITE_SENSITIVITY_BY_ROLE: Final[dict[Role, Sensitivity]] = {
    Role.MEMBER: Sensitivity.CONFIDENTIAL,
    Role.ADMIN: Sensitivity.SECRET,
    Role.OWNER: Sensitivity.SECRET,
}


@dataclass(frozen=True, slots=True)
class ResourceRef:
    scope: ScopeRef
    sensitivity: Sensitivity = Sensitivity.INTERNAL


class AccessControl:
    """Pure-Python policy decisions. Stateless; instantiate per request as needed."""

    def role_for(self, principal: Principal, scope: ScopeRef) -> Role | None:
        if principal.is_superuser:
            return Role.OWNER
        return principal.role_for(scope)

    def can_read(self, principal: Principal, resource: ResourceRef) -> bool:
        if principal.is_superuser:
            return True
        role = self.role_for(principal, resource.scope)
        if role is None:
            return False
        max_read = _READ_SENSITIVITY_BY_ROLE.get(role)
        if max_read is None:
            return False
        return _SENSITIVITY_RANK[resource.sensitivity] <= _SENSITIVITY_RANK[max_read]

    def can_write(self, principal: Principal, resource: ResourceRef) -> bool:
        if principal.is_superuser:
            return True
        role = self.role_for(principal, resource.scope)
        if role is None:
            return False
        max_write = _WRITE_SENSITIVITY_BY_ROLE.get(role)
        if max_write is None:
            return False
        return _SENSITIVITY_RANK[resource.sensitivity] <= _SENSITIVITY_RANK[max_write]

    def can_admin(self, principal: Principal, scope: ScopeRef) -> bool:
        if principal.is_superuser:
            return True
        role = self.role_for(principal, scope)
        if role is None:
            return False
        return _ROLE_RANK[role] >= _ROLE_RANK[Role.ADMIN]

    def can_own(self, principal: Principal, scope: ScopeRef) -> bool:
        if principal.is_superuser:
            return True
        return self.role_for(principal, scope) == Role.OWNER

    def is_admin_anywhere(self, principal: Principal) -> bool:
        """True if the principal is admin/owner on at least one scope (or super)."""
        if principal.is_superuser:
            return True
        return any(_ROLE_RANK[role] >= _ROLE_RANK[Role.ADMIN] for role in principal.roles.values())

    def visible_scopes(
        self,
        principal: Principal,
        types: set[ScopeType] | None = None,
    ) -> list[ScopeRef]:
        if principal.is_superuser:
            return []  # superuser is unscoped — caller treats this as "all"
        scopes = [scope for scope in principal.roles if types is None or scope.type in types]
        return scopes

    def require(
        self,
        ok: bool,
        *,
        action: str,
        resource: ResourceRef | ScopeRef | None = None,
    ) -> None:
        if ok:
            return
        msg = f"access denied for action {action!r}"
        if resource is not None:
            msg += f" on {resource}"
        raise AccessDeniedError(msg)
