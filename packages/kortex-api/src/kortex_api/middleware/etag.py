"""ETag / If-Match enforcement.

Memories use the ``updated_at`` timestamp as their version token. PATCH on
``/v1/memories/{id}`` may include ``If-Match: <etag>``; if the current row's
ETag doesn't match, we reject with 412 Precondition Failed.

The check runs inside a dedicated middleware so handlers stay clean; the
ETag header is also stamped on successful GET responses.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from kortex_core.db.session import session_scope
from kortex_core.telemetry.logging import get_logger

log = get_logger("kortex.api.etag")

_MEMORY_PATCH_RE = re.compile(r"^/v1/memories/([0-9a-fA-F-]{36})$")


def _row_etag(updated_at_iso: str) -> str:
    return 'W/"' + hashlib.sha1(updated_at_iso.encode()).hexdigest()[:16] + '"'  # noqa: S324


class EtagMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        match = _MEMORY_PATCH_RE.match(request.url.path)
        if match and request.method == "PATCH":
            if_match = request.headers.get("if-match")
            if if_match:
                public_id = match.group(1)
                expected = await _current_etag_for_memory(public_id)
                if expected is None:
                    # Let the handler return 404 itself.
                    return await call_next(request)
                if if_match.strip() != expected:
                    return JSONResponse(
                        status_code=412,
                        content={
                            "type": "about:blank",
                            "title": "Precondition Failed",
                            "status": 412,
                            "detail": "ETag mismatch",
                        },
                        media_type="application/problem+json",
                    )
        return await call_next(request)


async def _current_etag_for_memory(public_id: str) -> str | None:
    try:
        async with session_scope() as s:
            row = (
                await s.execute(
                    text(
                        "SELECT updated_at FROM memories "
                        "WHERE public_id = CAST(:pid AS uuid) "
                        "AND deleted_at IS NULL"
                    ),
                    {"pid": public_id},
                )
            ).first()
    except Exception as e:  # noqa: BLE001
        log.warning("etag_lookup_failed", error=str(e))
        return None
    if not row:
        return None
    return _row_etag(str(row[0]))


# Re-exported so the ``memories`` router can stamp ETag on GET responses.
def etag_for_updated_at(updated_at_iso: str) -> str:
    return _row_etag(updated_at_iso)
