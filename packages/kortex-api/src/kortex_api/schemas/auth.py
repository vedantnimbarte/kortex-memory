"""Auth schemas."""

from __future__ import annotations

import uuid

from pydantic import EmailStr, Field

from kortex_api.schemas.common import APIModel


class LoginIn(APIModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class TokenOut(APIModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class WhoamiOut(APIModel):
    user_id: int
    public_id: uuid.UUID
    is_superuser: bool
    org_id: int
