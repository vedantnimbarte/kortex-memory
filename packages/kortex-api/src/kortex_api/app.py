"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from kortex_core.db.engine import close_engine
from kortex_core.settings import get_settings
from kortex_core.telemetry.logging import configure_logging
from kortex_core.telemetry.otel import configure_otel

from kortex_api.errors import http_exception_handler
from kortex_api.middleware.context import RequestContextMiddleware
from kortex_api.routers import (
    api_keys,
    auth,
    conversations,
    health,
    ingest,
    memories,
    orgs,
    projects,
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
    app.add_middleware(RequestContextMiddleware)

    app.add_exception_handler(HTTPException, http_exception_handler)

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
    app.include_router(search.router)
    app.include_router(ingest.router)

    return app


app = create_app()
