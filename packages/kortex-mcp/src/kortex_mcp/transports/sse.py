"""SSE transport for the Kortex MCP server.

Exposes the same tool registry as the stdio runner over HTTP using the upstream
``mcp.server.sse.SseServerTransport``. Authentication is per-connection: every
SSE request must carry ``Authorization: Bearer <kx_…>``; the bearer is
materialised into a Principal via :class:`kortex_core.services.auth_service`.

The resolved Principal is bound to the ``current_principal`` context-var for the
lifetime of the connection's ``server.run`` loop (each ``GET /sse`` is its own
asyncio task with its own context), so concurrent tenants are fully isolated —
we never write a process-global principal here.
"""

from __future__ import annotations

import logging

from kortex_core.db.session import session_scope
from kortex_core.security.principal import (
    Principal,
    reset_principal,
    set_principal,
)
from kortex_core.telemetry.logging import configure_logging
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from kortex_mcp.auth import McpAuthError, principal_from_api_key
from kortex_mcp.server import build_server

logger = logging.getLogger(__name__)


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        return None
    if not header.lower().startswith("bearer "):
        return None
    return header.split(" ", 1)[1].strip() or None


async def _resolve_principal(api_key: str) -> Principal:
    async with session_scope() as s:
        return await principal_from_api_key(s, api_key)


def build_app() -> Starlette:
    """Build the Starlette ASGI app that hosts the SSE MCP server.

    The two endpoints are:
      * ``GET /sse``      — long-lived SSE connection
      * ``POST /messages``— JSON-RPC posts from the client
    """
    configure_logging()
    server = build_server()
    sse = SseServerTransport("/messages/")

    async def sse_endpoint(request: Request) -> Response:
        token = _extract_bearer(request)
        if not token:
            return JSONResponse({"error": "missing bearer token"}, status_code=401)
        try:
            principal = await _resolve_principal(token)
        except McpAuthError as e:
            return JSONResponse({"error": str(e)}, status_code=401)

        # Bind this connection's principal to its own task context for the whole
        # server.run loop; tool handlers dispatched from this loop read it via
        # current_principal(). Reset on disconnect. No process-global state.
        ctx_token = set_principal(principal)
        try:
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
                read_stream, write_stream = streams
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )
        finally:
            reset_principal(ctx_token)
        return Response(status_code=204)

    return Starlette(
        debug=False,
        routes=[
            Route("/sse", endpoint=sse_endpoint),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )


def run_sse(host: str = "0.0.0.0", port: int = 8765) -> None:  # noqa: S104
    import uvicorn

    uvicorn.run(build_app(), host=host, port=port, log_level="info")
