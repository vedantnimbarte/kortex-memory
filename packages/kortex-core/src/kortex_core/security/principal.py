"""Principal: who is making this request.

A :class:`Principal` is set by the API/MCP middleware via :func:`set_principal`
and read implicitly by services and repositories through :func:`current_principal`.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Self

from kortex_core.db.types import ActorKind, Role, ScopeType, Sensitivity


@dataclass(frozen=True, slots=True)
class ScopeRef:
    """A polymorphic ``(scope_type, scope_id)`` pointer."""

    type: ScopeType
    id: int

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.type.value}:{self.id}"


@dataclass(frozen=True, slots=True)
class Principal:
    actor_id: int
    actor_kind: ActorKind
    org_id: int
    # Explicit scope this principal is acting within (for api keys bound to a scope).
    scope: ScopeRef | None = None
    # Effective role per scope (computed at auth time from memberships).
    roles: dict[ScopeRef, Role] = field(default_factory=dict)
    # API-key scopes (e.g. {"read:memory", "write:memory"}). Empty for users.
    key_scopes: frozenset[str] = field(default_factory=frozenset)
    # Maximum sensitivity this principal may read/write (derived from highest role).
    max_sensitivity: Sensitivity = Sensitivity.INTERNAL
    # Whether this is a superuser principal — bypasses tenancy. Use sparingly.
    is_superuser: bool = False

    def role_for(self, scope: ScopeRef) -> Role | None:
        return self.roles.get(scope)

    def has_key_scope(self, name: str) -> bool:
        return not self.key_scopes or name in self.key_scopes

    def with_role_added(self, scope: ScopeRef, role: Role) -> Self:
        new_roles = dict(self.roles)
        new_roles[scope] = role
        return type(self)(
            actor_id=self.actor_id,
            actor_kind=self.actor_kind,
            org_id=self.org_id,
            scope=self.scope,
            roles=new_roles,
            key_scopes=self.key_scopes,
            max_sensitivity=self.max_sensitivity,
            is_superuser=self.is_superuser,
        )


_principal_var: ContextVar[Principal | None] = ContextVar("kortex_principal", default=None)


def set_principal(principal: Principal | None) -> object:
    """Bind a principal to the current context. Returns a token to reset later."""
    return _principal_var.set(principal)


def reset_principal(token: object) -> None:
    _principal_var.reset(token)  # type: ignore[arg-type]


def current_principal() -> Principal | None:
    return _principal_var.get()


def require_principal() -> Principal:
    p = current_principal()
    if p is None:
        raise PermissionError("No authenticated principal in context")
    return p
