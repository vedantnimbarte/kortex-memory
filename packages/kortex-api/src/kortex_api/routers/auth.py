"""Auth router: login, whoami."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from kortex_core.db.types import ActorKind
from kortex_core.repositories.user_repo import UserRepository
from kortex_core.services.account_service import AccountError, AccountService
from kortex_core.services.auth_service import AuthError, AuthService
from kortex_core.services.signup_service import SignupError, SignupService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import bad_request, conflict, not_found, unauthorized
from kortex_api.schemas.auth import (
    EmailIn,
    LoginIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    RefreshIn,
    RegisterIn,
    TokenIn,
    TokenOut,
    WhoamiOut,
)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn, session: SessionDep) -> TokenOut:
    auth = AuthService(session)
    try:
        result = await auth.login_with_password(email=payload.email, password=payload.password)
    except AuthError as e:
        raise unauthorized(str(e)) from e
    await session.commit()
    return TokenOut(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
    )


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(payload: RegisterIn, session: SessionDep) -> TokenOut:
    signup = SignupService(session)
    try:
        result = await signup.register(
            email=payload.email,
            password=payload.password,
            org_name=payload.org_name,
            display_name=payload.display_name,
        )
    except SignupError as e:
        raise conflict(str(e)) from e
    return TokenOut(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
    )


@router.post("/refresh", response_model=TokenOut)
async def refresh(payload: RefreshIn, session: SessionDep) -> TokenOut:
    # ponytail: stateless refresh, no rotation/revocation blocklist — add a
    # jti denylist (redis) if session revocation becomes a requirement.
    auth = AuthService(session)
    try:
        result = await auth.refresh(payload.refresh_token)
    except AuthError as e:
        raise unauthorized(str(e)) from e
    await session.commit()
    return TokenOut(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=result.expires_in,
    )


@router.post("/logout", status_code=204)
async def logout(payload: RefreshIn, session: SessionDep) -> None:
    # Revokes the refresh token's jti (best-effort). Access tokens are short-lived
    # and expire on their own.
    await AuthService(session).revoke_refresh(payload.refresh_token)


@router.post("/password-reset/request", status_code=202)
async def request_password_reset(payload: PasswordResetRequestIn, session: SessionDep) -> dict:
    # Always 202 — never reveal whether the email is registered.
    await AccountService(session).request_password_reset(payload.email)
    return {"status": "accepted"}


@router.post("/password-reset/confirm", status_code=204)
async def confirm_password_reset(payload: PasswordResetConfirmIn, session: SessionDep) -> None:
    try:
        await AccountService(session).confirm_password_reset(payload.token, payload.new_password)
    except AccountError as e:
        raise bad_request(str(e)) from e


@router.post("/verify-email/confirm", status_code=204)
async def confirm_email(payload: TokenIn, session: SessionDep) -> None:
    try:
        await AccountService(session).confirm_verification(payload.token)
    except AccountError as e:
        raise bad_request(str(e)) from e


@router.post("/verify-email/resend", status_code=202)
async def resend_verification(payload: EmailIn, session: SessionDep) -> dict:
    await AccountService(session).resend_verification(payload.email)
    return {"status": "accepted"}


@router.post("/verify-email/send", status_code=202)
async def send_my_verification(principal: PrincipalDep, session: SessionDep) -> dict:
    # Authenticated resend for the logged-in user (no email in the body).
    if principal.actor_kind != ActorKind.USER:
        raise bad_request("only user sessions can request verification")
    users = UserRepository(session, principal=principal)
    user = await users.get_by_id(principal.actor_id)
    if user is None:
        raise not_found("user not found")
    if not user.email_verified:
        await AccountService(session).send_verification(user_id=user.id, email=user.email)
    return {"status": "accepted"}


@router.get("/whoami", response_model=WhoamiOut)
async def whoami(principal: PrincipalDep, session: SessionDep) -> WhoamiOut:
    public_id: uuid.UUID
    email_verified = True
    if principal.actor_kind == ActorKind.USER:
        users = UserRepository(session, principal=principal)
        user = await users.get_by_id(principal.actor_id)
        if user is None:
            raise not_found("user not found")
        public_id = user.public_id
        email_verified = user.email_verified
    else:
        public_id = uuid.UUID(int=0)
    return WhoamiOut(
        user_id=principal.actor_id,
        public_id=public_id,
        is_superuser=principal.is_superuser,
        org_id=principal.org_id,
        email_verified=email_verified,
    )
