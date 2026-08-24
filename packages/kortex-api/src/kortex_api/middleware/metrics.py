"""Prometheus HTTP metrics.

Emits the request counter and latency histogram the Grafana dashboards and the
API HPA (``kortex_api_requests_total`` custom-metric autoscaling) depend on.
Labels use the matched *route template* (e.g. ``/v1/memories/{public_id}``) not
the raw path, so per-object UUIDs don't explode label cardinality.

Also exports write-path health (WU-1.3). Those three gauges are refreshed from
the database on scrape rather than pushed by the worker, because the worker has
no HTTP surface to scrape. The result is cached for
``_EMBED_GAUGE_TTL_SECONDS`` so an unauthenticated ``/metrics`` cannot be turned
into a database load generator.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUESTS = Counter(
    "kortex_api_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
DURATION = Histogram(
    "kortex_api_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)


EMBED_PENDING = Gauge(
    "kortex_embed_pending",
    "Memories accepted but not yet embedded (invisible to vector search)",
)
EMBED_FAILED = Gauge(
    "kortex_embed_failed",
    "Memories parked after exhausting embedding retries",
)
EMBED_OLDEST_PENDING = Gauge(
    "kortex_embed_oldest_pending_seconds",
    "Age of the oldest memory still waiting to be embedded",
)

# ponytail: one aggregate query per scrape window, cached in-process. If a
# multi-replica API makes the duplicated queries matter, move the refresh into
# the worker and publish through Redis.
_EMBED_GAUGE_TTL_SECONDS = 15.0
_embed_gauges_refreshed_at = 0.0


async def refresh_embed_gauges() -> None:
    """Repopulate the write-path gauges, at most once per TTL.

    Never raises: a metrics endpoint that 500s during a database blip takes the
    monitoring away exactly when it is needed.
    """
    global _embed_gauges_refreshed_at
    now = time.monotonic()
    if now - _embed_gauges_refreshed_at < _EMBED_GAUGE_TTL_SECONDS:
        return
    _embed_gauges_refreshed_at = now

    from kortex_core.db.session import session_scope
    from kortex_core.db.types import ActorKind
    from kortex_core.repositories.memory_repo import MemoryRepository
    from kortex_core.security.principal import Principal

    try:
        async with session_scope() as session:
            repo = MemoryRepository(
                session,
                principal=Principal(
                    actor_id=0, actor_kind=ActorKind.SYSTEM, org_id=0, is_superuser=True
                ),
            )
            counts = await repo.embed_status_counts()
    except Exception:  # pragma: no cover - metrics must not break on db trouble
        return
    EMBED_PENDING.set(counts.pending)
    EMBED_FAILED.set(counts.failed)
    EMBED_OLDEST_PENDING.set(counts.oldest_pending_seconds)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


async def metrics_endpoint(_request: Request | None = None) -> Response:
    await refresh_embed_gauges()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)
        start = time.perf_counter()
        response = await call_next(request)
        path = _route_template(request)
        REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        DURATION.labels(request.method, path).observe(time.perf_counter() - start)
        return response
