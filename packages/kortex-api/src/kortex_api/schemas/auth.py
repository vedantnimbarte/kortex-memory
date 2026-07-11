"""Auth schemas."""

from __future__ import annotations

import uuid

from pydantic import EmailStr, Field

from kortex_api.schemas.common import APIModel


class LoginIn(APIModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class RefreshIn(APIModel):
    refresh_token: str


class RegisterIn(APIModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    org_name: str = Field(min_length=1, max_length=200)
    display_name: str = Field(default="", max_length=200)


class PasswordResetRequestIn(APIModel):
    email: EmailStr


class PasswordResetConfirmIn(APIModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=200)


class TokenIn(APIModel):
    token: str = Field(min_length=1)


class EmailIn(APIModel):
    email: EmailStr


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
    email_verified: bool = True
