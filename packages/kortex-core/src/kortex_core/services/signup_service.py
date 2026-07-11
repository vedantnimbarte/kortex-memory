"""Self-serve signup: create org + owner user + a starter workspace/project.

Public (unauthenticated) flow, so it runs under an internal superuser principal
bound to the freshly-created org. Grants the new user OWNER at every scope it
creates — there is no role cascade (org OWNER does NOT inherit workspace/project
access), so the memberships must be explicit or the user can't write memories.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import ActorKind, Role, ScopeType
from kortex_core.security.principal import Principal
from kortex_core.services.account_service import AccountService
from kortex_core.services.auth_service import AuthService, LoginResult
from kortex_core.services.org_service import OrgService
from kortex_core.services.project_service import ProjectService
from kortex_core.services.user_service import UserService
from kortex_core.services.workspace_service import WorkspaceService


class SignupError(Exception):
    """Raised when signup can't complete (e.g. email/slug already taken)."""


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s or "org")[:56]


class SignupService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def register(
        self, *, email: str, password: str, org_name: str, display_name: str = ""
    ) -> LoginResult:
        users_probe = UserService(self._session, _super(0))
        if await users_probe.get_by_email(email) is not None:
            raise SignupError("an account with this email already exists")

        # Unique-ish slug; the DB unique constraint is the real guard.
        slug = f"{slugify(org_name)}-{uuid.uuid4().hex[:6]}"

        try:
            org = await OrgService(self._session, _super(0)).create(
                slug=slug, name=org_name, plan="free"
            )
            org_admin = _super(org.id)
            ws = await WorkspaceService(self._session, org_admin).create(
                slug="default", name="Default workspace"
            )
            project = await ProjectService(self._session, org_admin).create(
                workspace_public_id=ws.public_id, slug="default", name="Default project"
            )
            assert project is not None  # just created the workspace

            users = UserService(self._session, org_admin)
            user = await users.create_with_password(
                email=email, password=password, display_name=display_name
            )
            for scope_type, scope_id in (
                (ScopeType.ORG, org.id),
                (ScopeType.WORKSPACE, ws.id),
                (ScopeType.PROJECT, project.id),
            ):
                await users.grant(
                    user_id=user.id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    role=Role.OWNER,
                )
        except IntegrityError as e:
            await self._session.rollback()
            raise SignupError("email or org name already in use") from e

        await self._session.commit()
        # Fire the verification email (non-blocking: the account is usable now,
        # the UI just nudges until it's confirmed).
        await AccountService(self._session).send_verification(user_id=user.id, email=user.email)
        return AuthService.issue_tokens(user.id, user.public_id)


def _super(org_id: int) -> Principal:
    return Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=org_id,
        is_superuser=True,
    )
