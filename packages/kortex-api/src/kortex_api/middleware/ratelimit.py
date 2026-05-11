"""Per-key rate-limit middleware.

Limits are stamped against the API-key prefix (or actor id for JWT-auth'd
users). Three buckets:

  * **read**   — GETs and HEADs (default 600/min)
  * **recall** — POST /v1/search/recall (default 30/min)
  * **write**  — all other mutating verbs (default 120/min)

If Redis is unavailable we **fail open**: the middleware logs a warning but
never blocks a request. Auth still runs through the API-key chokepoint, so a
broker outage doesn't punch a hole through tenancy — only through quota.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import redis.asyncio as redis_async
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from kortex_core.security.api_keys import parse_api_key
from kortex_core.security.rate_limit import RateLimiter
from kortex_core.settings import get_settings
from kortex_core.telemetry.logging import get_logger

log = get_logger("kortex.api.ratelimit")


def _bucket_for_path_method(path: str, method: str) -> str | None:
    if path.startswith("/livez") or path.startswith("/readyz") or path == "/metrics":
        return None
    if path == "/v1/search/recall":
        return "recall"
    if method in {"GET", "HEAD"}:
        return "read"
    return "write"


def _extract_key_id(request: Request) -> str | None:
    """Identify the caller for bucketing. Prefers the API-key prefix."""
    raw = request.headers.get("x-api-key")
    if not raw:
        authz = request.headers.get("authorization") or ""
        if authz.lower().startswith("bearer kx_"):
            raw = authz.split(" ", 1)[1]
    if raw:
        parsed = parse_api_key(raw)
        if parsed:
            return f"key:{parsed[0]}"
        return None
    if authz := request.headers.get("authorization"):
        # JWT-auth'd user; we don't decode here — the route does. Bucket per IP
        # instead of leaking the token across the rate-limit key.
        client = request.client.host if request.client else "unknown"
        return f"ip:{client}"
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_url: str | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._client: redis_async.Redis | None = None
        self._limiter: RateLimiter | None = None
        self._redis_url = redis_url or get_settings().redis_url

    def _get_limiter(self) -> RateLimiter | None:
        if self._limiter is not None:
            return self._limiter
        try:
            self._client = redis_async.from_url(self._redis_url)
            self._limiter = RateLimiter(self._client)
        except Exception as e:  # noqa: BLE001
            log.warning("ratelimit_redis_unavailable", error=str(e))
            return None
        return self._limiter

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        bucket = _bucket_for_path_method(request.url.path, request.method)
        if bucket is None:
            return await call_next(request)

        key_id = _extract_key_id(request)
        if key_id is None:
            return await call_next(request)

        limiter = self._get_limiter()
        if limiter is None:
            return await call_next(request)

        s = get_settings()
        capacity = {
            "read": s.rate_limit_read_per_min,
            "write": s.rate_limit_write_per_min,
            "recall": s.rate_limit_recall_per_min,
        }[bucket]

        try:
            decision = await limiter.check(
                key=f"{bucket}:{key_id}",
                capacity=capacity,
                window_seconds=60,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("ratelimit_check_failed", error=str(e))
            return await call_next(request)

        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "type": "about:blank",
                    "title": "Too Many Requests",
                    "status": 429,
                    "detail": f"rate limit exceeded for bucket {bucket}",
                },
                media_type="application/problem+json",
                headers={
                    "Retry-After": str(max(1, decision.retry_after_ms // 1000)),
                },
            )
        return await call_next(request)
