"""Idempotency-Key middleware.

Clients posting non-idempotent requests can supply ``Idempotency-Key: <uuid>``;
we cache the response body+status for 24h keyed by ``(principal, key, method,
path, body-hash)`` and replay it on retry. Concurrent duplicates are guarded by
a Redis reservation (SET NX): the first request in-flight wins, and a second
request arriving with the same key before the first completes gets ``409`` (or
a replay once the first has finished) rather than executing twice. If Redis is
unavailable we fail open (request proceeds normally) — the goal is to absorb
client-side retries, not to enforce strict at-most-once semantics.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable

import redis.asyncio as redis_async
from kortex_core.security.api_keys import parse_api_key
from kortex_core.settings import get_settings
from kortex_core.telemetry.logging import get_logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = get_logger("kortex.api.idempotency")

_CACHE_PREFIX = "idem:"
_CACHE_TTL_SECONDS = 24 * 3600
_INFLIGHT_TTL_SECONDS = 60
_INFLIGHT_SENTINEL = "\x00inflight"


def _principal_token(request: Request) -> str:
    # An x-api-key credential is always an API key, even if it fails to parse —
    # classify by header source so it never collides with a JWT bucket.
    raw_key = request.headers.get("x-api-key")
    if raw_key:
        parsed = parse_api_key(raw_key)
        return f"k:{parsed[0] if parsed else raw_key[:12]}"
    authz = request.headers.get("authorization") or ""
    if authz.lower().startswith("bearer "):
        # JWT — a 12-char prefix so we don't store full tokens in cache keys.
        return f"j:{authz.split(' ', 1)[1][:12]}"
    return "anon"


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_url: str | None = None) -> None:
        super().__init__(app)
        self._client: redis_async.Redis | None = None
        self._redis_url = redis_url or get_settings().redis_url

    def _get_client(self) -> redis_async.Redis | None:
        if self._client is not None:
            return self._client
        try:
            self._client = redis_async.from_url(self._redis_url)
        except Exception as e:
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

        # Bind the key to the request body so replaying a key with a different
        # payload can't silently return the old response.
        body = await request.body()
        body_hash = hashlib.sha256(body).hexdigest()[:16]
        cache_key = (
            f"{_CACHE_PREFIX}{_principal_token(request)}:"
            f"{request.method}:{request.url.path}:{key}:{body_hash}"
        )

        replay = await self._try_replay(client, cache_key)
        if replay is not None:
            return replay

        # Reserve the key: the first request in-flight wins; a concurrent
        # duplicate that can't reserve and has no cached result yet is rejected.
        try:
            reserved = await client.set(
                cache_key, _INFLIGHT_SENTINEL, nx=True, ex=_INFLIGHT_TTL_SECONDS
            )
        except Exception as e:
            log.warning("idempotency_reserve_failed", error=str(e))
            reserved = True  # fail open
        if not reserved:
            replay = await self._try_replay(client, cache_key)
            if replay is not None:
                return replay
            return JSONResponse(
                status_code=409,
                media_type="application/problem+json",
                content={
                    "type": "about:blank",
                    "title": "Conflict",
                    "status": 409,
                    "detail": "a request with this Idempotency-Key is in progress",
                },
            )

        try:
            response = await call_next(request)
        except Exception:
            # Don't leave the reservation blocking legitimate retries.
            try:
                await client.delete(cache_key)
            except Exception:
                pass
            raise

        # Only cache successful 2xx bodies. Avoid 5xx / 4xx replays that could
        # paper over genuine server bugs.
        if 200 <= response.status_code < 300:
            body = b""
            async for chunk in response.body_iterator:  # type: ignore[attr-defined]
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
            except Exception as e:
                log.warning("idempotency_set_failed", error=str(e))
            return Response(
                content=body,
                status_code=response.status_code,
                media_type=response.media_type,
                headers=dict(response.headers),
            )
        # Non-2xx: drop the reservation so a corrected retry isn't blocked.
        try:
            await client.delete(cache_key)
        except Exception:
            pass
        return response

    async def _try_replay(self, client: redis_async.Redis, cache_key: str) -> Response | None:
        """Return a replayed response for a completed request, else None."""
        try:
            cached = await client.get(cache_key)
        except Exception as e:
            log.warning("idempotency_get_failed", error=str(e))
            return None
        if not cached:
            return None
        if cached in (_INFLIGHT_SENTINEL, _INFLIGHT_SENTINEL.encode()):
            return None  # reservation held, no result yet
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
            except Exception:
                pass
            return None
