"""Auth router: login, whoami."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from kortex_core.db.types import ActorKind
from kortex_core.repositories.user_repo import UserRepository
from kortex_core.services.auth_service import AuthError, AuthService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import not_found, unauthorized
from kortex_api.schemas.auth import LoginIn, TokenOut, WhoamiOut

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn, session: SessionDep) -> TokenOut:
    auth = AuthService(session)
    try:
        result = await auth.login_with_password(
            email=payload.email, password=payload.password
        )
    except AuthError as e:
        raise unauthorized(str(e)) from e
    await session.commit()
    return TokenOut(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
    )


@router.get("/whoami", response_model=WhoamiOut)
async def whoami(principal: PrincipalDep, session: SessionDep) -> WhoamiOut:
    public_id: uuid.UUID
    if principal.actor_kind == ActorKind.USER:
        users = UserRepository(session, principal=principal)
        user = await users.get_by_id(principal.actor_id)
        if user is None:
            raise not_found("user not found")
        public_id = user.public_id
    else:
        public_id = uuid.UUID(int=0)
    return WhoamiOut(
        user_id=principal.actor_id,
        public_id=public_id,
        is_superuser=principal.is_superuser,
        org_id=principal.org_id,
    )
