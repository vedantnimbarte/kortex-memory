"""User service: invite, grant/revoke memberships."""

from __future__ import annotations

import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.audit import AuditAction
from kortex_core.db.types import Role, ScopeType
from kortex_core.models.user import Membership, User
from kortex_core.repositories.audit_repo import AuditRepository
from kortex_core.repositories.membership_repo import MembershipRepository
from kortex_core.repositories.user_repo import UserRepository
from kortex_core.security.passwords import hash_password
from kortex_core.security.principal import Principal, ScopeRef
from kortex_core.services.access_control import AccessControl, AccessDeniedError


class UserService:
    def __init__(self, session: AsyncSession, principal: Principal):
        self._session = session
        self._principal = principal
        self._ac = AccessControl()
        self._users = UserRepository(session, principal=principal)
        self._memberships = MembershipRepository(session, principal=principal)

    async def list_org_members(self) -> list[tuple[User, str]]:
        """Members of the caller's org, each with their org-level role."""
        return await self._memberships.list_org_members(self._principal.org_id)

    async def invite_member(self, *, email: str, role: Role) -> User:
        """Invite by email: create the account if new (temp password), grant an
        org membership, and return the user. The caller emails a set-password
        link separately. Reuses create_with_password's admin gate."""
        user = await self._users.get_by_email(email)
        if user is None:
            user = await self.create_with_password(email=email, password=secrets.token_urlsafe(24))
        await self.grant(
            user_id=user.id,
            scope_type=ScopeType.ORG,
            scope_id=self._principal.org_id,
            role=role,
        )
        return user

    async def create_with_password(
        self,
        *,
        email: str,
        password: str,
        display_name: str = "",
        is_superuser: bool = False,
    ) -> User:
        # Only superusers or scope admins may mint accounts (prevents anonymous
        # user-table spam and orphan-account creation).
        if not self._ac.is_admin_anywhere(self._principal):
            raise AccessDeniedError("not authorized to create users")
        return await self._users.create(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
            is_superuser=is_superuser,
        )

    async def get_by_email(self, email: str) -> User | None:
        return await self._users.get_by_email(email)

    async def get(self, public_id: uuid.UUID) -> User | None:
        return await self._users.get_by_public_id(public_id)

    async def grant(
        self,
        *,
        user_id: int,
        scope_type: ScopeType,
        scope_id: int,
        role: Role,
    ) -> Membership:
        target = ScopeRef(type=scope_type, id=scope_id)
        # Caller must administer the target scope. Granting OWNER requires OWNER.
        # role_for() only matches the caller's OWN memberships, so a caller from
        # org A cannot grant anything on org B — this closes the takeover hole.
        allowed = (
            self._ac.can_own(self._principal, target)
            if role == Role.OWNER
            else self._ac.can_admin(self._principal, target)
        )
        if not allowed:
            raise AccessDeniedError(f"not authorized to grant {role.value} on {target}")
        membership = await self._memberships.grant(
            user_id=user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            role=role,
        )
        await self._audit(
            AuditAction.MEMBER_GRANTED,
            user_id=user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            role=role.value,
        )
        return membership

    async def revoke(self, *, user_id: int, scope_type: ScopeType, scope_id: int) -> bool:
        target = ScopeRef(type=scope_type, id=scope_id)
        if not self._ac.can_admin(self._principal, target):
            raise AccessDeniedError(f"not authorized to revoke on {target}")
        revoked = await self._memberships.revoke(
            user_id=user_id, scope_type=scope_type, scope_id=scope_id
        )
        if revoked:
            await self._audit(
                AuditAction.MEMBER_REVOKED,
                user_id=user_id,
                scope_type=scope_type,
                scope_id=scope_id,
            )
        return revoked

    async def _audit(
        self,
        action: AuditAction,
        *,
        user_id: int,
        scope_type: ScopeType,
        scope_id: int,
        role: str | None = None,
    ) -> None:
        """Record a membership change.

        The target is the *user* whose access changed, not the scope: "who can
        reach this" is the question an access review asks, and answering it
        from scope-keyed rows means a join the reviewer has to know to make.
        """
        await AuditRepository(self._session, principal=self._principal).append(
            actor_kind=self._principal.actor_kind,
            actor_id=self._principal.actor_id,
            action=str(action),
            target_type="user",
            target_id=user_id,
            metadata={
                "scope_type": scope_type.value,
                "scope_id": scope_id,
                **({"role": role} if role else {}),
            },
        )
