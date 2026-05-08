"""User schemas."""

from __future__ import annotations

from pydantic import EmailStr, Field

from kortex_core.db.types import Role, ScopeType

from kortex_api.schemas.common import APIModel, TimestampedOut


class UserIn(APIModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = ""
    is_superuser: bool = False


class UserOut(TimestampedOut):
    email: EmailStr
    display_name: str
    is_superuser: bool


class GrantIn(APIModel):
    scope_type: ScopeType
    scope_id: int
    role: Role
