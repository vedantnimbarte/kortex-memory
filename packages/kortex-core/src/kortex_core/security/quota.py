"""Per-org daily quotas (cost ceilings).

Distinct from the per-minute rate limiter: this bounds *cumulative* daily use of
expensive, model-backed operations so no single tenant can drive an unbounded
LLM/embedding bill within the per-minute allowance. Backed by a Redis counter
that resets each UTC day.
"""

from __future__ import annotations

import datetime as dt

import redis.asyncio as redis_async

from kortex_core.settings import get_settings
from kortex_core.telemetry.logging import get_logger

log = get_logger("kortex.quota")

_client: redis_async.Redis | None = None


def _get_client() -> redis_async.Redis | None:
    global _client
    if _client is None:
        try:
            _client = redis_async.from_url(get_settings().redis_url)
        except Exception as e:
            log.warning("quota_redis_unavailable", error=str(e))
            return None
    return _client


async def check_daily_quota(*, bucket: str, org_id: int, limit: int) -> bool:
    """Increment the org's daily counter for ``bucket``; return True if still
    within ``limit``. ``limit <= 0`` disables the cap. Fails open on Redis error
    (a brief blip shouldn't take down the recall path; per-request cost is
    already bounded by the retrieval loop caps).
    """
    if limit <= 0:
        return True
    client = _get_client()
    if client is None:
        return True
    day = dt.datetime.now(tz=dt.UTC).strftime("%Y%m%d")
    key = f"quota:{bucket}:{org_id}:{day}"
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, 86_400 + 3_600)  # day + slack
        return count <= limit
    except Exception as e:
        log.warning("quota_check_failed", error=str(e))
        return True
