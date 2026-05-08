"""Seed a dev org/workspace/project + admin user + scoped api key.

Run after ``alembic upgrade head``::

    uv run python scripts/seed_dev.py

Prints the freshly minted API key plaintext exactly once. Save it.
"""

from __future__ import annotations

import asyncio
import os
import sys

from kortex_core.db.session import session_scope
from kortex_core.db.types import ActorKind, Role, ScopeType
from kortex_core.repositories.org_repo import OrgRepository
from kortex_core.repositories.user_repo import UserRepository
from kortex_core.repositories.workspace_repo import WorkspaceRepository
from kortex_core.security.principal import Principal
from kortex_core.services.api_key_service import ApiKeyService
from kortex_core.services.project_service import ProjectService
from kortex_core.services.user_service import UserService
from kortex_core.services.workspace_service import WorkspaceService


def _superuser(org_id: int = 0) -> Principal:
    return Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=org_id,
        is_superuser=True,
    )


async def main() -> int:
    admin_email = os.environ.get("KORTEX_SEED_EMAIL", "admin@kortex.local")
    admin_password = os.environ.get("KORTEX_SEED_PASSWORD", "kortex-dev-password")
    org_slug = os.environ.get("KORTEX_SEED_ORG", "kortex")
    ws_slug = os.environ.get("KORTEX_SEED_WORKSPACE", "default")
    proj_slug = os.environ.get("KORTEX_SEED_PROJECT", "playground")

    async with session_scope() as session:
        sys_principal = _superuser()

        # --- org ---
        org_repo = OrgRepository(session, principal=sys_principal)
        org = await org_repo.get_by_slug(org_slug)
        if org is None:
            org = await org_repo.create(
                slug=org_slug, name=org_slug.capitalize(), plan="dev"
            )

        org_principal = _superuser(org.id)

        # --- user (superuser for dev) ---
        users = UserRepository(session, principal=org_principal)
        existing = await users.get_by_email(admin_email)
        if existing is None:
            user_svc = UserService(session, org_principal)
            user = await user_svc.create_with_password(
                email=admin_email,
                password=admin_password,
                display_name="Admin",
                is_superuser=True,
            )
        else:
            user = existing

        # --- workspace ---
        ws_repo = WorkspaceRepository(session, principal=org_principal)
        ws = await ws_repo.get_by_slug(ws_slug)
        if ws is None:
            ws_svc = WorkspaceService(session, org_principal)
            ws = await ws_svc.create(slug=ws_slug, name=ws_slug.capitalize())

        # --- project ---
        proj_svc = ProjectService(session, org_principal)
        proj = await proj_svc.create(
            workspace_public_id=ws.public_id, slug=proj_slug, name=proj_slug.capitalize()
        )
        if proj is None:
            print("workspace lookup failed", file=sys.stderr)
            return 2

        # --- memberships (admin gets owner everywhere) ---
        user_svc = UserService(session, org_principal)
        await user_svc.grant(
            user_id=user.id,
            scope_type=ScopeType.ORG,
            scope_id=org.id,
            role=Role.OWNER,
        )
        await user_svc.grant(
            user_id=user.id,
            scope_type=ScopeType.WORKSPACE,
            scope_id=ws.id,
            role=Role.OWNER,
        )
        await user_svc.grant(
            user_id=user.id,
            scope_type=ScopeType.PROJECT,
            scope_id=proj.id,
            role=Role.OWNER,
        )

        # --- api key bound to the project ---
        key_svc = ApiKeyService(session, org_principal)
        minted = await key_svc.mint(
            name="dev-key",
            scopes=["read:memory", "write:memory", "read:attachment", "write:attachment"],
            scope_type=ScopeType.PROJECT,
            scope_id=proj.id,
        )

    print("=" * 60)
    print("kortex dev seed complete")
    print(f"  org:        {org_slug} (id={org.id})")
    print(f"  workspace:  {ws_slug} (id={ws.id})")
    print(f"  project:    {proj_slug} (id={proj.id})")
    print(f"  admin:      {admin_email} / {admin_password}")
    print(f"  api key:    {minted.plaintext}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
