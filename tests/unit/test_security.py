"""Unit tests for security primitives."""

from __future__ import annotations

import pytest
from kortex_core.security.api_keys import (
    generate_api_key,
    parse_api_key,
    verify_api_key_secret,
)
from kortex_core.security.jwt import JwtError, decode_jwt, encode_jwt
from kortex_core.security.passwords import hash_password, verify_password

pytestmark = pytest.mark.unit


def test_password_roundtrip() -> None:
    h = hash_password("hunter2hunter2")
    assert verify_password(h, "hunter2hunter2")
    assert not verify_password(h, "wrong-password")


def test_api_key_roundtrip() -> None:
    material = generate_api_key()
    parsed = parse_api_key(material.plaintext)
    assert parsed is not None
    prefix, secret = parsed
    assert prefix == material.prefix
    assert secret == material.secret
    assert verify_api_key_secret(secret, material.secret_hash)
    assert not verify_api_key_secret("not-the-secret", material.secret_hash)


def test_api_key_malformed() -> None:
    assert parse_api_key("garbage") is None
    assert parse_api_key("kx_short") is None
    assert parse_api_key("notkx_aaaaaaaa_" + "b" * 43) is None


def test_jwt_roundtrip() -> None:
    token = encode_jwt(subject="42", extra={"role": "admin"})
    payload = decode_jwt(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_jwt_tampered() -> None:
    token = encode_jwt(subject="42")
    with pytest.raises(JwtError):
        decode_jwt(token + "x")


def test_jwt_type_enforced() -> None:
    """A refresh token must not be accepted where an access token is required."""
    refresh = encode_jwt(subject="42", token_type="refresh")
    with pytest.raises(JwtError, match="expected 'access'"):
        decode_jwt(refresh, expected_type="access")
    # The matching type still decodes.
    access = encode_jwt(subject="42", token_type="access")
    assert decode_jwt(access, expected_type="access")["sub"] == "42"
