"""Prometheus HTTP metrics.

Emits the request counter and latency histogram the Grafana dashboards and the
API HPA (``kortex_api_requests_total`` custom-metric autoscaling) depend on.
Labels use the matched *route template* (e.g. ``/v1/memories/{public_id}``) not
the raw path, so per-object UUIDs don't explode label cardinality.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
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


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


def metrics_endpoint() -> Response:
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
