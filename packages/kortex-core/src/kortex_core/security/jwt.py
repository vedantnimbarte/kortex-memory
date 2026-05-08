"""JWT helpers."""

from __future__ import annotations

import datetime as dt
from typing import Any

import jwt

from kortex_core.settings import get_settings


class JwtError(Exception):
    """Raised on invalid/expired/tampered JWTs."""


def encode_jwt(
    *,
    subject: str,
    extra: dict[str, Any] | None = None,
    ttl_seconds: int | None = None,
    token_type: str = "access",
) -> str:
    s = get_settings()
    now = dt.datetime.now(tz=dt.UTC)
    ttl = ttl_seconds or s.jwt_access_ttl_seconds
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(seconds=ttl)).timestamp()),
        "type": token_type,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm)


def decode_jwt(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret.get_secret_value(), algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError as e:
        raise JwtError(str(e)) from e
