"""SSE transport for the Kortex MCP server.

Exposes the same tool registry as the stdio runner over HTTP using the upstream
``mcp.server.sse.SseServerTransport``. Authentication is per-connection: every
SSE request must carry ``Authorization: Bearer <kx_…>``; the bearer is
materialised into a Principal via :class:`kortex_core.services.auth_service`.

Per-connection runtime binding is process-global today (one principal at a
time, mirroring stdio). M9 will refactor the transport to attach the principal
to the request scope itself once the SDK exposes a hook for per-call context.
"""

from __future__ import annotations

import logging

from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from kortex_core.db.session import session_scope
from kortex_core.telemetry.logging import configure_logging

from kortex_mcp.auth import McpAuthError, principal_from_api_key
from kortex_mcp.context import McpRuntime, set_runtime
from kortex_mcp.server import build_server

logger = logging.getLogger(__name__)


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        return None
    if not header.lower().startswith("bearer "):
        return None
    return header.split(" ", 1)[1].strip() or None


async def _resolve_principal(api_key: str) -> None:
    async with session_scope() as s:
        principal = await principal_from_api_key(s, api_key)
    set_runtime(McpRuntime(principal=principal))


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
            return JSONResponse(
                {"error": "missing bearer token"}, status_code=401
            )
        try:
            await _resolve_principal(token)
        except McpAuthError as e:
            return JSONResponse({"error": str(e)}, status_code=401)

        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            read_stream, write_stream = streams
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
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
