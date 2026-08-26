"""Auth service: login, JWT mint, principal materialization."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.audit import AuditAction
from kortex_core.db.types import ActorKind, Role, ScopeType, Sensitivity
from kortex_core.repositories.api_key_repo import ApiKeyRepository
from kortex_core.repositories.audit_repo import AuditRepository
from kortex_core.repositories.membership_repo import MembershipRepository
from kortex_core.repositories.user_repo import UserRepository
from kortex_core.security import token_denylist
from kortex_core.security.api_keys import (
    parse_api_key,
    verify_api_key_secret,
)
from kortex_core.security.jwt import JwtError, decode_jwt, encode_jwt
from kortex_core.security.passwords import verify_password
from kortex_core.security.principal import Principal, ScopeRef
from kortex_core.services.access_control import AccessControl
from kortex_core.settings import get_settings


class AuthError(Exception):
    """Raised on invalid credentials/token."""


@dataclass(frozen=True, slots=True)
class LoginResult:
    user_id: int
    user_public_id: uuid.UUID
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class PrincipalLoad:
    """Result of materializing a principal from a credential."""

    principal: Principal


_KEY_ROLE_TO_SENSITIVITY = {
    Role.VIEWER: Sensitivity.CONFIDENTIAL,
    Role.MEMBER: Sensitivity.CONFIDENTIAL,
    Role.ADMIN: Sensitivity.SECRET,
    Role.OWNER: Sensitivity.SECRET,
}


class AuthService:
    """Stateless service; use a fresh instance per request."""

    def __init__(self, session: AsyncSession):
        self._session = session
        # The auth service is one of the rare callers that work without a
        # bound principal — it is the thing that creates the principal.
        self._users = UserRepository(session)
        self._memberships = MembershipRepository(session)

    # --- token mint (shared by login, refresh, signup) ---

    @staticmethod
    def issue_tokens(user_id: int, user_public_id: uuid.UUID) -> LoginResult:
        s = get_settings()
        access = encode_jwt(
            subject=str(user_id),
            extra={"jti": str(uuid.uuid4())},
            ttl_seconds=s.jwt_access_ttl_seconds,
            token_type="access",
        )
        refresh = encode_jwt(
            subject=str(user_id),
            extra={"jti": str(uuid.uuid4())},
            ttl_seconds=s.jwt_refresh_ttl_seconds,
            token_type="refresh",
        )
        return LoginResult(
            user_id=user_id,
            user_public_id=user_public_id,
            access_token=access,
            refresh_token=refresh,
            expires_in=s.jwt_access_ttl_seconds,
        )

    # --- user/password login ---

    async def login_with_password(self, *, email: str, password: str) -> LoginResult:
        user = await self._users.get_by_email(email)
        if user is None or user.password_hash is None:
            # Not audited. An unknown email belongs to no tenant, so there is no
            # org whose log it could honestly go in, and writing it to a guessed
            # one would fill a customer's audit trail with strangers. Failed
            # logins against addresses that do not exist belong in the
            # application log, which is where the rate limiter already sees them.
            raise AuthError("invalid credentials")
        if not verify_password(user.password_hash, password):
            await self._audit_auth(user.id, AuditAction.LOGIN_FAILED)
            raise AuthError("invalid credentials")
        await self._users.touch_login(user.id)
        await self._audit_auth(user.id, AuditAction.LOGIN)
        return self.issue_tokens(user.id, user.public_id)

    async def _audit_auth(self, user_id: int, action: AuditAction) -> None:
        """Record an authentication event against the user's org.

        Never records the password, or a hash of it, or its length: a
        failed-login log that captures credential material is a credential
        store with a misleading name, and it is the first thing an attacker
        reads after getting query access.

        A user with no org membership is skipped rather than filed under a
        placeholder tenant — an entry in the wrong org's log is worse than a
        missing one, because it will be believed.
        """
        org_id = await self._org_for_user(user_id)
        if org_id is None:
            return
        await AuditRepository(self._session).append(
            actor_kind=ActorKind.USER,
            actor_id=user_id,
            action=str(action),
            target_type="user",
            target_id=user_id,
            org_id=org_id,
        )

    async def _org_for_user(self, user_id: int) -> int | None:
        memberships = await self._memberships.list_for_user(user_id)
        return next(
            (m.scope_id for m in memberships if m.scope_type == ScopeType.ORG.value),
            None,
        )

    async def refresh(self, refresh_token: str) -> LoginResult:
        """Exchange a valid refresh token for a fresh pair. Rotation: the spent
        token's jti is revoked, so a refresh token is single-use — a replayed or
        stolen-then-used token is rejected on its second use."""
        try:
            payload = decode_jwt(refresh_token, expected_type="refresh")
        except JwtError as e:
            raise AuthError(f"invalid refresh token: {e}") from e
        jti = payload.get("jti", "")
        if await token_denylist.is_revoked(jti):
            raise AuthError("refresh token has been revoked")
        sub = payload.get("sub")
        try:
            user_id = int(sub) if sub else None
        except (TypeError, ValueError) as e:
            raise AuthError("token subject not an integer") from e
        if user_id is None:
            raise AuthError("token missing subject")
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise AuthError("user not found")
        await self._revoke_payload(payload)  # rotate: burn the used token
        return self.issue_tokens(user.id, user.public_id)

    async def revoke_refresh(self, refresh_token: str) -> None:
        """Revoke a refresh token (logout). Silently succeeds on a bad token —
        logout should never error on an already-invalid credential."""
        try:
            payload = decode_jwt(refresh_token, expected_type="refresh")
        except JwtError:
            return
        await self._revoke_payload(payload)

    @staticmethod
    async def _revoke_payload(payload: dict) -> None:
        jti = payload.get("jti", "")
        exp = payload.get("exp")
        ttl = get_settings().jwt_refresh_ttl_seconds
        if isinstance(exp, int | float):
            ttl = max(1, int(exp - dt.datetime.now(tz=dt.UTC).timestamp()))
        await token_denylist.revoke(jti, ttl_seconds=ttl)

    # --- principal materialization ---

    async def principal_from_jwt(self, token: str) -> PrincipalLoad:
        try:
            payload = decode_jwt(token, expected_type="access")
        except JwtError as e:
            raise AuthError(f"invalid token: {e}") from e
        sub = payload.get("sub")
        if not sub:
            raise AuthError("token missing subject")
        try:
            user_id = int(sub)
        except (TypeError, ValueError) as e:
            raise AuthError("token subject not an integer") from e

        user = await self._users.get_by_id(user_id)
        if user is None:
            raise AuthError("user not found")

        memberships = await self._memberships.list_for_user(user.id)
        roles: dict[ScopeRef, Role] = {}
        for m in memberships:
            try:
                scope_type = ScopeType(m.scope_type)
                role = Role(m.role)
            except ValueError:  # pragma: no cover - data corruption
                continue
            roles[ScopeRef(type=scope_type, id=m.scope_id)] = role

        # Pick org from first org-scoped membership (or 0 for unscoped superuser).
        org_id = next(
            (s.id for s in roles if s.type == ScopeType.ORG),
            0,
        )

        max_sensitivity = self._max_sensitivity(roles.values())

        principal = Principal(
            actor_id=user.id,
            actor_kind=ActorKind.USER,
            org_id=org_id,
            roles=roles,
            key_scopes=frozenset(),
            max_sensitivity=max_sensitivity,
            is_superuser=user.is_superuser,
        )
        return PrincipalLoad(principal=principal)

    async def principal_from_api_key(self, plaintext: str) -> PrincipalLoad:
        parsed = parse_api_key(plaintext)
        if parsed is None:
            raise AuthError("malformed api key")
        prefix, secret = parsed
        keys = ApiKeyRepository(self._session, principal=_superuser_principal())
        key = await keys.get_active_by_prefix(prefix)
        if key is None or not verify_api_key_secret(secret, key.key_hash):
            raise AuthError("invalid api key")
        await keys.touch_used(key)

        # The bound scope on the key drives the visible scope set; we don't
        # cross-cut user memberships here (api keys are scoped explicitly).
        roles: dict[ScopeRef, Role] = {}
        if key.scope_type and key.scope_id:
            try:
                roles[ScopeRef(type=ScopeType(key.scope_type), id=key.scope_id)] = Role.MEMBER
            except ValueError:  # pragma: no cover
                pass
        max_sensitivity = self._max_sensitivity(roles.values())

        principal = Principal(
            actor_id=key.id,
            actor_kind=ActorKind.API_KEY,
            org_id=key.org_id,
            scope=next(iter(roles), None),
            roles=roles,
            key_scopes=frozenset(key.scopes),
            max_sensitivity=max_sensitivity,
        )
        return PrincipalLoad(principal=principal)

    @staticmethod
    def _max_sensitivity(roles: Iterable[Role]) -> Sensitivity:
        # Highest sensitivity any role grants read access to.
        best = Sensitivity.PUBLIC
        ranks = {
            Sensitivity.PUBLIC: 1,
            Sensitivity.INTERNAL: 2,
            Sensitivity.CONFIDENTIAL: 3,
            Sensitivity.SECRET: 4,
        }
        for role in roles:
            cap = _KEY_ROLE_TO_SENSITIVITY.get(role, Sensitivity.PUBLIC)
            if ranks[cap] > ranks[best]:
                best = cap
        return best


def _superuser_principal() -> Principal:
    """Internal-only super principal for queries that must run before a real
    principal is bound (e.g. API-key lookup at auth time).
    """
    return Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=0,
        is_superuser=True,
    )


__all__ = [
    "AccessControl",
    "AuthError",
    "AuthService",
    "LoginResult",
    "PrincipalLoad",
]
