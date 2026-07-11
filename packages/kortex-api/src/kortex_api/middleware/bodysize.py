"""Request body-size guard.

Rejects oversized request bodies up front (413) so a single giant POST can't
OOM the event loop or amplify downstream work. Enforced from the declared
``Content-Length``; the setting ``api_request_max_bytes`` was previously defined
but never wired in.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from kortex_core.settings import get_settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._max_bytes = max_bytes or get_settings().api_request_max_bytes

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_bytes:
                    return self._too_large()
            except ValueError:
                pass  # malformed header — let the server handle it
        return await call_next(request)

    def _too_large(self) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Payload Too Large",
                "status": 413,
                "detail": f"request body exceeds {self._max_bytes} bytes",
            },
        )
