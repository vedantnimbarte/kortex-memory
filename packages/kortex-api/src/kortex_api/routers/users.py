"""Users router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from kortex_core.db.types import ActorKind
from kortex_core.services.account_service import AccountService
from kortex_core.services.user_service import UserService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import forbidden, not_found
from kortex_api.schemas.user import (
    GrantIn,
    InviteIn,
    OrgMemberOut,
    UserIn,
    UserOut,
)

router = APIRouter(prefix="/v1/users", tags=["users"])


@router.get("", response_model=list[OrgMemberOut])
async def list_members(principal: PrincipalDep, session: SessionDep) -> list[OrgMemberOut]:
    svc = UserService(session, principal)
    return [
        OrgMemberOut(
            public_id=u.public_id,
            email=u.email,
            display_name=u.display_name,
            role=role,
            email_verified=u.email_verified,
        )
        for (u, role) in await svc.list_org_members()
    ]


@router.post("/invite", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def invite_member(payload: InviteIn, principal: PrincipalDep, session: SessionDep) -> UserOut:
    svc = UserService(session, principal)
    user = await svc.invite_member(email=payload.email, role=payload.role)
    await session.commit()
    # Email the invitee a set-password link (invite wording, 7-day link).
    await AccountService(session).send_invite(payload.email)
    return UserOut.model_validate(user)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserIn, principal: PrincipalDep, session: SessionDep) -> UserOut:
    if payload.is_superuser and not principal.is_superuser:
        raise forbidden("only superusers may create superusers")
    svc = UserService(session, principal)
    user = await svc.create_with_password(
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        is_superuser=payload.is_superuser,
    )
    await session.commit()
    return UserOut.model_validate(user)


@router.get("/{public_id}", response_model=UserOut)
async def get_user(public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> UserOut:
    svc = UserService(session, principal)
    user = await svc.get(public_id)
    if user is None:
        raise not_found("user not found")
    # Users are global rows; only reveal a user's PII to themselves or a
    # superuser (otherwise any tenant could enumerate every user's email).
    is_self = principal.actor_kind == ActorKind.USER and principal.actor_id == user.id
    if not (principal.is_superuser or is_self):
        raise not_found("user not found")
    return UserOut.model_validate(user)


@router.post("/{public_id}/memberships", status_code=status.HTTP_204_NO_CONTENT)
async def grant_membership(
    public_id: uuid.UUID,
    payload: GrantIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> None:
    svc = UserService(session, principal)
    user = await svc.get(public_id)
    if user is None:
        raise not_found("user not found")
    await svc.grant(
        user_id=user.id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        role=payload.role,
    )
    await session.commit()


@router.delete("/{public_id}/memberships", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_membership(
    public_id: uuid.UUID,
    payload: GrantIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> None:
    svc = UserService(session, principal)
    user = await svc.get(public_id)
    if user is None:
        raise not_found("user not found")
    await svc.revoke(user_id=user.id, scope_type=payload.scope_type, scope_id=payload.scope_id)
    await session.commit()
