"""Per-request context: request_id and principal contextvar binding."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from kortex_core.security.principal import reset_principal, set_principal
from kortex_core.telemetry.logging import request_id_var


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        rid_token = request_id_var.set(rid)
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
            request_id_var.reset(rid_token)
