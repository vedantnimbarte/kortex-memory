"""Account self-service: password reset + email verification.

All flows are public (unauthenticated), so they run under an internal superuser
principal. Tokens are short-lived JWTs with dedicated ``type`` claims (``reset``,
``verify``) so a reset token can't be used as an access token and vice-versa.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import ActorKind
from kortex_core.notifications import send_email
from kortex_core.repositories.user_repo import UserRepository
from kortex_core.security.jwt import JwtError, decode_jwt, encode_jwt
from kortex_core.security.passwords import hash_password
from kortex_core.security.principal import Principal
from kortex_core.settings import get_settings

_RESET_TTL = 30 * 60  # 30 min
_VERIFY_TTL = 24 * 60 * 60  # 24 h
_INVITE_TTL = 7 * 24 * 60 * 60  # 7 days — invitees need longer to act


class AccountError(Exception):
    """Raised on an invalid/expired reset or verification token."""


class AccountService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._users = UserRepository(session, principal=_super())

    # --- password reset ---

    async def request_password_reset(self, email: str) -> None:
        """Send a reset link if the email exists. Always returns None — never
        reveal whether an account exists (enumeration guard)."""
        user = await self._users.get_by_email(email)
        if user is None or user.password_hash is None:
            return
        token = encode_jwt(
            subject=str(user.id),
            ttl_seconds=_RESET_TTL,
            token_type="reset",
        )
        url = f"{get_settings().web_base_url}/reset-password?token={token}"
        await send_email(
            to=user.email,
            subject="Reset your Kortex password",
            body=f"Reset your password: {url}\n\nThis link expires in 30 minutes.",
        )

    async def confirm_password_reset(self, token: str, new_password: str) -> None:
        user_id = self._subject(token, "reset")
        await self._users.set_password(user_id, hash_password(new_password))
        await self._session.commit()

    async def send_invite(self, email: str, *, org_name: str = "") -> None:
        """Email a new teammate a set-password link (reset token, longer TTL)."""
        user = await self._users.get_by_email(email)
        if user is None:
            return
        token = encode_jwt(
            subject=str(user.id),
            ttl_seconds=_INVITE_TTL,
            token_type="reset",
        )
        url = f"{get_settings().web_base_url}/reset-password?token={token}"
        where = f" to {org_name}" if org_name else ""
        await send_email(
            to=email,
            subject="You've been invited to Kortex",
            body=(
                f"You've been added{where} on Kortex. Set your password to get "
                f"started:\n\n{url}\n\nThis link expires in 7 days."
            ),
        )

    # --- email verification ---

    async def send_verification(self, *, user_id: int, email: str) -> None:
        token = encode_jwt(
            subject=str(user_id),
            ttl_seconds=_VERIFY_TTL,
            token_type="verify",
        )
        url = f"{get_settings().web_base_url}/verify-email?token={token}"
        await send_email(
            to=email,
            subject="Verify your Kortex email",
            body=f"Confirm your email: {url}\n\nThis link expires in 24 hours.",
        )

    async def confirm_verification(self, token: str) -> None:
        user_id = self._subject(token, "verify")
        await self._users.set_email_verified(user_id, True)
        await self._session.commit()

    async def resend_verification(self, email: str) -> None:
        user = await self._users.get_by_email(email)
        if user is not None and not user.email_verified:
            await self.send_verification(user_id=user.id, email=user.email)

    # --- helpers ---

    def _subject(self, token: str, expected_type: str) -> int:
        try:
            payload = decode_jwt(token, expected_type=expected_type)
        except JwtError as e:
            raise AccountError(f"invalid or expired token: {e}") from e
        sub = payload.get("sub")
        try:
            return int(sub) if sub else 0
        except (TypeError, ValueError) as e:
            raise AccountError("malformed token subject") from e


def _super() -> Principal:
    return Principal(actor_id=0, actor_kind=ActorKind.SYSTEM, org_id=0, is_superuser=True)
