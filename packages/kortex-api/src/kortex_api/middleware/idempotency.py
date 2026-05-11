"""Idempotency-Key middleware.

Clients posting non-idempotent requests can supply ``Idempotency-Key: <uuid>``;
we cache the response body+status for 24h keyed by ``(principal, key, method,
path)`` and replay it on retry. Replay is opportunistic: if Redis is
unavailable we fail open (request proceeds normally) — the goal is to absorb
client-side retries, not to enforce strict at-most-once semantics.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import redis.asyncio as redis_async
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from kortex_core.security.api_keys import parse_api_key
from kortex_core.settings import get_settings
from kortex_core.telemetry.logging import get_logger

log = get_logger("kortex.api.idempotency")

_CACHE_PREFIX = "idem:"
_CACHE_TTL_SECONDS = 24 * 3600


def _principal_token(request: Request) -> str:
    raw = request.headers.get("x-api-key")
    if not raw:
        authz = request.headers.get("authorization") or ""
        if authz.lower().startswith("bearer "):
            raw = authz.split(" ", 1)[1]
    if not raw:
        return "anon"
    parsed = parse_api_key(raw)
    if parsed:
        return f"k:{parsed[0]}"
    # JWT — hash a 12-char prefix so we don't store full tokens in cache keys.
    return f"j:{raw[:12]}"


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_url: str | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._client: redis_async.Redis | None = None
        self._redis_url = redis_url or get_settings().redis_url

    def _get_client(self) -> redis_async.Redis | None:
        if self._client is not None:
            return self._client
        try:
            self._client = redis_async.from_url(self._redis_url)
        except Exception as e:  # noqa: BLE001
            log.warning("idempotency_redis_unavailable", error=str(e))
            return None
        return self._client

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Only mutating methods need idempotency.
        if request.method not in {"POST", "PATCH", "PUT", "DELETE"}:
            return await call_next(request)
        key = request.headers.get("idempotency-key")
        if not key or len(key) > 200:
            return await call_next(request)

        client = self._get_client()
        if client is None:
            return await call_next(request)

        cache_key = (
            f"{_CACHE_PREFIX}{_principal_token(request)}:"
            f"{request.method}:{request.url.path}:{key}"
        )

        try:
            cached = await client.get(cache_key)
        except Exception as e:  # noqa: BLE001
            log.warning("idempotency_get_failed", error=str(e))
            cached = None

        if cached:
            try:
                blob = json.loads(cached)
                return Response(
                    content=blob["body"],
                    status_code=int(blob["status"]),
                    media_type=blob.get("media_type") or "application/json",
                    headers={**blob.get("headers", {}), "Idempotent-Replay": "true"},
                )
            except (ValueError, KeyError):  # corrupted entry — drop it
                try:
                    await client.delete(cache_key)
                except Exception:  # noqa: BLE001
                    pass

        response = await call_next(request)

        # Only cache successful 2xx bodies. Avoid 5xx / 4xx replays that could
        # paper over genuine server bugs.
        if 200 <= response.status_code < 300:
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            payload = json.dumps(
                {
                    "status": response.status_code,
                    "body": body.decode("utf-8", errors="replace"),
                    "media_type": response.media_type,
                    "headers": {
                        k: v
                        for k, v in response.headers.items()
                        if k.lower() not in {"content-length", "transfer-encoding"}
                    },
                }
            )
            try:
                await client.set(cache_key, payload, ex=_CACHE_TTL_SECONDS)
            except Exception as e:  # noqa: BLE001
                log.warning("idempotency_set_failed", error=str(e))
            return Response(
                content=body,
                status_code=response.status_code,
                media_type=response.media_type,
                headers=dict(response.headers),
            )
        return response
