"""Token-bucket rate limiter backed by Redis.

The bucket lives at ``rl:{key}`` with capacity ``capacity`` and refill rate
``capacity/window_seconds`` per second. The Lua script is atomic and constant-time.
"""

from __future__ import annotations

from dataclasses import dataclass

import redis.asyncio as redis_async

# Redis Lua: returns (allowed:int, retry_after_ms:int)
_LUA_TOKEN_BUCKET = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])

if tokens == nil then
  tokens = capacity
  ts = now_ms
end

local elapsed = math.max(0, now_ms - ts) / 1000.0
tokens = math.min(capacity, tokens + elapsed * refill_per_sec)

local allowed = 0
local retry = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  retry = math.ceil(((cost - tokens) / refill_per_sec) * 1000)
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now_ms)
redis.call('PEXPIRE', key, math.ceil((capacity / refill_per_sec) * 1000) + 1000)

return {allowed, retry}
"""


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_ms: int


class RateLimiter:
    """Async token-bucket limiter."""

    def __init__(self, client: redis_async.Redis):
        self._client = client
        self._script = client.register_script(_LUA_TOKEN_BUCKET)

    async def check(
        self, *, key: str, capacity: int, window_seconds: int, cost: int = 1
    ) -> RateLimitDecision:
        import time

        now_ms = int(time.time() * 1000)
        refill = capacity / max(window_seconds, 1)
        result = await self._script(keys=[f"rl:{key}"], args=[capacity, refill, now_ms, cost])
        allowed = bool(result[0])
        retry = int(result[1])
        return RateLimitDecision(allowed=allowed, retry_after_ms=retry)
