"""API key generation, parsing, and verification.

Format: ``kx_<prefix8>_<secret43>``. The ``prefix`` is queryable; the ``secret``
is hashed via argon2id and never stored in cleartext.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from kortex_core.settings import get_settings

_KEY_PREFIX = "kx"
_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

_hasher = PasswordHasher(time_cost=2, memory_cost=64 * 1024, parallelism=4)


@dataclass(frozen=True, slots=True)
class ApiKeyMaterial:
    """The plaintext material of a freshly minted API key. Show once, never store."""

    plaintext: str
    prefix: str
    secret: str
    secret_hash: str


def _random_token(length: int) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def generate_api_key() -> ApiKeyMaterial:
    """Mint a new API key. Caller must persist ``prefix`` and ``secret_hash`` and
    return ``plaintext`` to the user exactly once.
    """
    s = get_settings()
    prefix = _random_token(s.api_key_prefix_length)
    secret = _random_token(s.api_key_secret_length)
    plaintext = f"{_KEY_PREFIX}_{prefix}_{secret}"
    secret_hash = _hasher.hash(secret)
    return ApiKeyMaterial(plaintext=plaintext, prefix=prefix, secret=secret, secret_hash=secret_hash)


def parse_api_key(plaintext: str) -> tuple[str, str] | None:
    """Split a plaintext API key into ``(prefix, secret)``. Returns ``None`` on
    malformed input. Constant-time-ish: rejects fast on shape, slow auth happens
    in :func:`verify_api_key_secret`.
    """
    parts = plaintext.split("_", 2)
    if len(parts) != 3 or parts[0] != _KEY_PREFIX:
        return None
    prefix, secret = parts[1], parts[2]
    s = get_settings()
    if len(prefix) != s.api_key_prefix_length or len(secret) != s.api_key_secret_length:
        return None
    return prefix, secret


def hash_api_key_secret(secret: str) -> str:
    return _hasher.hash(secret)


def verify_api_key_secret(secret: str, secret_hash: str) -> bool:
    try:
        _hasher.verify(secret_hash, secret)
    except VerifyMismatchError:
        return False
    return True
