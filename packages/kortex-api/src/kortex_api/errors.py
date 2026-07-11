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
    return ProblemDetail(status_code=status.HTTP_403_FORBIDDEN, title="Forbidden", detail=detail)


def not_found(detail: str = "not found") -> ProblemDetail:
    return ProblemDetail(status_code=status.HTTP_404_NOT_FOUND, title="Not Found", detail=detail)


def conflict(detail: str) -> ProblemDetail:
    return ProblemDetail(status_code=status.HTTP_409_CONFLICT, title="Conflict", detail=detail)


def too_many_requests(detail: str) -> ProblemDetail:
    return ProblemDetail(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        title="Too Many Requests",
        detail=detail,
    )


def bad_request(detail: str) -> ProblemDetail:
    return ProblemDetail(
        status_code=status.HTTP_400_BAD_REQUEST, title="Bad Request", detail=detail
    )


def service_unavailable(detail: str) -> ProblemDetail:
    return ProblemDetail(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        title="Service Unavailable",
        detail=detail,
    )


def payment_required(detail: str) -> ProblemDetail:
    return ProblemDetail(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        title="Plan Limit Reached",
        detail=detail,
    )


async def access_denied_handler(_: Request, exc: Exception) -> JSONResponse:
    """Map service-layer authorization failures to RFC 7807 403 responses."""
    problem = forbidden(str(exc) or "forbidden")
    return JSONResponse(
        status_code=problem.status_code,
        content=problem.detail,
        media_type="application/problem+json",
    )


async def quota_exceeded_handler(_: Request, exc: Exception) -> JSONResponse:
    """Map plan-limit failures to RFC 7807 402 responses."""
    problem = payment_required(str(exc) or "plan limit reached")
    return JSONResponse(
        status_code=problem.status_code,
        content=problem.detail,
        media_type="application/problem+json",
    )


async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    # exc.detail is typed `str` by Starlette but we pass dict problem-details
    # through it; treat it as object so the isinstance narrowing is valid.
    detail: object = exc.detail
    if isinstance(detail, dict) and "type" in detail:
        return JSONResponse(
            status_code=exc.status_code,
            content=detail,
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
