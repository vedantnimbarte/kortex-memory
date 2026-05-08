"""Argon2id password hashing."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Time cost = 2, memory = 64 MiB, parallelism = 4 — matches plan §J for api keys.
_hasher = PasswordHasher(time_cost=2, memory_cost=64 * 1024, parallelism=4)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(hash_: str, password: str) -> bool:
    try:
        _hasher.verify(hash_, password)
    except VerifyMismatchError:
        return False
    return True


def needs_rehash(hash_: str) -> bool:
    return _hasher.check_needs_rehash(hash_)
