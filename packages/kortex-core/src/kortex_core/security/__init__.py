"""Security primitives: passwords, api keys, JWT, rate limit, principal."""

from kortex_core.security.api_keys import (
    ApiKeyMaterial,
    generate_api_key,
    hash_api_key_secret,
    parse_api_key,
    verify_api_key_secret,
)
from kortex_core.security.jwt import decode_jwt, encode_jwt
from kortex_core.security.passwords import hash_password, verify_password
from kortex_core.security.principal import (
    Principal,
    ScopeRef,
    current_principal,
    require_principal,
    set_principal,
)

__all__ = [
    "ApiKeyMaterial",
    "Principal",
    "ScopeRef",
    "current_principal",
    "decode_jwt",
    "encode_jwt",
    "generate_api_key",
    "hash_api_key_secret",
    "hash_password",
    "parse_api_key",
    "require_principal",
    "set_principal",
    "verify_api_key_secret",
    "verify_password",
]
