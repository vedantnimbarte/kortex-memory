"""RFC 7807 ProblemDetails errors."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse


class ProblemDetail(HTTPException):
    """RFC 7807 problem detail HTTPException."""

    def __init__(
        self,
        *,
        status_code: int,
        title: str,
        detail: str | None = None,
        type_: str = "about:blank",
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        body: dict[str, Any] = {"type": type_, "title": title, "status": status_code}
        if detail:
            body["detail"] = detail
        if extra:
            body.update(extra)
        super().__init__(status_code=status_code, detail=body, headers=headers)


def unauthorized(detail: str = "authentication required") -> ProblemDetail:
    return ProblemDetail(
        status_code=status.HTTP_401_UNAUTHORIZED,
        title="Unauthorized",
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def forbidden(detail: str = "forbidden") -> ProblemDetail:
    return ProblemDetail(
        status_code=status.HTTP_403_FORBIDDEN, title="Forbidden", detail=detail
    )


def not_found(detail: str = "not found") -> ProblemDetail:
    return ProblemDetail(
        status_code=status.HTTP_404_NOT_FOUND, title="Not Found", detail=detail
    )


def conflict(detail: str) -> ProblemDetail:
    return ProblemDetail(
        status_code=status.HTTP_409_CONFLICT, title="Conflict", detail=detail
    )


async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "type" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
            media_type="application/problem+json",
            headers=exc.headers,
        )
    body = {
        "type": "about:blank",
        "title": exc.__class__.__name__,
        "status": exc.status_code,
        "detail": str(exc.detail) if exc.detail else None,
    }
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        media_type="application/problem+json",
        headers=exc.headers,
    )
