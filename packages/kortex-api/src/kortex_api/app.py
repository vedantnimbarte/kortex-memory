"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from kortex_core.db.engine import close_engine
from kortex_core.security.plan_limits import QuotaExceededError
from kortex_core.services.access_control import AccessDeniedError
from kortex_core.settings import get_settings
from kortex_core.telemetry.logging import configure_logging
from kortex_core.telemetry.otel import configure_otel

from kortex_api.errors import (
    access_denied_handler,
    http_exception_handler,
    quota_exceeded_handler,
)
from kortex_api.middleware.bodysize import BodySizeLimitMiddleware
from kortex_api.middleware.context import RequestContextMiddleware
from kortex_api.middleware.etag import EtagMiddleware
from kortex_api.middleware.idempotency import IdempotencyMiddleware
from kortex_api.middleware.metrics import PrometheusMiddleware, metrics_endpoint
from kortex_api.middleware.ratelimit import RateLimitMiddleware
from kortex_api.routers import (
    admin,
    analytics,
    api_keys,
    attachments,
    audit,
    auth,
    billing,
    conversations,
    export,
    health,
    ingest,
    memories,
    memory_tool,
    orgs,
    projects,
    review,
    search,
    sessions,
    users,
    workspaces,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    configure_otel()
    yield
    await close_engine()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Kortex Memory API",
        version="0.1.0",
        description="Production-grade memory layer for LLMs and AI coding agents.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(PrometheusMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(EtagMiddleware)
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(RateLimitMiddleware)
    # Added last → outermost → runs first, so oversized bodies are rejected
    # before rate-limit/idempotency ever read them.
    app.add_middleware(BodySizeLimitMiddleware)

    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(AccessDeniedError, access_denied_handler)
    app.add_exception_handler(QuotaExceededError, quota_exceeded_handler)

    # Prometheus scrape endpoint (dashboards + HPA custom-metric autoscaling).
    app.add_route("/metrics", metrics_endpoint, include_in_schema=False)

    # Distributed tracing: instrument the app so spans are emitted when OTel is
    # enabled (no-op provider otherwise). The dependency was already declared.
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        pass

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(orgs.router)
    app.include_router(workspaces.router)
    app.include_router(projects.router)
    app.include_router(users.router)
    app.include_router(api_keys.router)
    app.include_router(sessions.router)
    app.include_router(conversations.router)
    app.include_router(memories.router)
    app.include_router(memory_tool.router)
    app.include_router(review.router)
    app.include_router(attachments.router)
    app.include_router(search.router)
    app.include_router(analytics.router)
    app.include_router(ingest.router)
    app.include_router(export.router)
    app.include_router(billing.router)
    app.include_router(admin.router)
    app.include_router(audit.router)

    return app


app = create_app()
