"""Per-request context: request_id, principal, and caller origin.

The origin (IP and user agent) is bound here rather than passed down because
the audit sites are five layers below the HTTP boundary, and a parameter
every future site has to remember to pass is a parameter some of them will
forget."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from kortex_core.security.principal import reset_principal, set_principal
from kortex_core.security.request_context import reset_origin, set_origin
from kortex_core.telemetry.logging import request_id_var
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        rid_token = request_id_var.set(rid)
        origin_tokens = set_origin(
            request.client.host if request.client else None,
            request.headers.get("user-agent"),
        )
        principal_token = None
        try:
            principal = getattr(request.state, "principal", None)
            if principal is not None:
                principal_token = set_principal(principal)
            response = await call_next(request)
            response.headers["x-request-id"] = rid
            return response
        finally:
            if principal_token is not None:
                reset_principal(principal_token)
            reset_origin(origin_tokens)
            request_id_var.reset(rid_token)
