"""Refresh-token revocation via a Redis jti denylist.

Backs two things: rotation (a refresh token is single-use — spending it revokes
its jti) and logout ("sign out" revokes the current refresh jti). Keys carry a
TTL equal to the token's remaining life, so the set self-trims.

Fails open on Redis errors (a blip shouldn't lock everyone out); access tokens
are short-lived, so the exposure window from a missed check is bounded.
"""

from __future__ import annotations

import redis.asyncio as redis_async

from kortex_core.settings import get_settings
from kortex_core.telemetry.logging import get_logger

log = get_logger("kortex.denylist")

_client: redis_async.Redis | None = None


def _get_client() -> redis_async.Redis | None:
    global _client
    if _client is None:
        try:
            _client = redis_async.from_url(get_settings().redis_url)
        except Exception as e:
            log.warning("denylist_redis_unavailable", error=str(e))
            return None
    return _client


def _key(jti: str) -> str:
    return f"revoked_jti:{jti}"


async def revoke(jti: str, *, ttl_seconds: int) -> None:
    """Mark a token jti revoked for ``ttl_seconds`` (its remaining lifetime)."""
    client = _get_client()
    if client is None or not jti:
        return
    try:
        await client.set(_key(jti), "1", ex=max(1, ttl_seconds))
    except Exception as e:
        log.warning("denylist_revoke_failed", error=str(e))


async def is_revoked(jti: str) -> bool:
    client = _get_client()
    if client is None or not jti:
        return False
    try:
        return bool(await client.exists(_key(jti)))
    except Exception as e:
        log.warning("denylist_check_failed", error=str(e))
        return False  # fail open
