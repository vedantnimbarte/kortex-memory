"""Access policy skill.

The M1 ``AccessControl`` service implements the RBAC × sensitivity matrix; this
module re-exports it through the ``Skill`` shape so M6+ swappable policies have
a single import path: ``kortex_core.skills.access_policy``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from kortex_core.db.types import Role, Sensitivity
from kortex_core.services.access_control import (
    AccessControl,
    AccessDeniedError,
    ResourceRef,
)


@runtime_checkable
class AccessPolicy(Protocol):
    """Any object that can answer can_read / can_write / can_admin."""

    name: str


class RoleSensitivityPolicy(AccessControl):
    """Plan's default policy (RBAC × sensitivity). Pure pass-through to AccessControl."""

    name = "role_sensitivity"


_singleton: AccessPolicy | None = None


def get_access_policy() -> AccessControl:
    global _singleton
    if _singleton is None:
        _singleton = RoleSensitivityPolicy()
    return _singleton  # type: ignore[return-value]


__all__ = [
    "AccessControl",
    "AccessDeniedError",
    "AccessPolicy",
    "ResourceRef",
    "Role",
    "RoleSensitivityPolicy",
    "Sensitivity",
    "get_access_policy",
]
