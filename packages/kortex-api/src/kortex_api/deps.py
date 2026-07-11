"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Request
from kortex_core.db.session import get_session
from kortex_core.security.principal import Principal
from kortex_core.services.auth_service import AuthError, AuthService
from sqlalchemy.ext.asyncio import AsyncSession

from kortex_api.errors import unauthorized


async def db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


async def authenticated_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(db_session),
) -> Principal:
    """Resolve a Principal from API key (preferred) or JWT bearer token."""
    auth = AuthService(session)

    api_key = x_api_key
    if api_key is None and authorization and authorization.lower().startswith("bearer kx_"):
        api_key = authorization.split(" ", 1)[1]
    if api_key:
        try:
            load = await auth.principal_from_api_key(api_key)
        except AuthError as e:
            raise unauthorized(str(e)) from e
        request.state.principal = load.principal
        return load.principal

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        try:
            load = await auth.principal_from_jwt(token)
        except AuthError as e:
            raise unauthorized(str(e)) from e
        request.state.principal = load.principal
        return load.principal

    raise unauthorized("missing Authorization or X-API-Key header")


PrincipalDep = Annotated[Principal, Depends(authenticated_principal)]
SessionDep = Annotated[AsyncSession, Depends(db_session)]
