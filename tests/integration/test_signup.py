"""Integration: self-serve signup creates a usable tenant."""

from __future__ import annotations

import pytest
from kortex_core.db.types import ScopeType
from kortex_core.services.auth_service import AuthService
from kortex_core.services.signup_service import SignupError, SignupService

pytestmark = pytest.mark.integration


async def test_register_creates_org_user_and_scopes(session) -> None:  # type: ignore[no-untyped-def]
    result = await SignupService(session).register(
        email="founder@acme.io", password="hunter2pass", org_name="Acme Inc"
    )
    assert result.access_token
    assert result.refresh_token
    assert result.user_id > 0

    # The new user can log in with the password we set.
    login = await AuthService(session).login_with_password(
        email="founder@acme.io", password="hunter2pass"
    )
    assert login.user_id == result.user_id

    # And is OWNER at org + workspace + project (no cascade — must be explicit).
    principal = (await AuthService(session).principal_from_jwt(result.access_token)).principal
    scope_types = {s.type for s in principal.roles}
    assert {ScopeType.ORG, ScopeType.WORKSPACE, ScopeType.PROJECT} <= scope_types


async def test_duplicate_email_rejected(session) -> None:  # type: ignore[no-untyped-def]
    await SignupService(session).register(
        email="dup@acme.io", password="hunter2pass", org_name="First Co"
    )
    with pytest.raises(SignupError):
        await SignupService(session).register(
            email="dup@acme.io", password="another-pass", org_name="Second Co"
        )
