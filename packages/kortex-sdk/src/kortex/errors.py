"""What went wrong, as something you can catch.

The API speaks RFC 7807, so every error body carries ``title`` and ``detail``.
Those are surfaced rather than an httpx status line, because "memory limit
reached for the free plan (25,000 memories)" is actionable and
``HTTPStatusError: 402`` is not.

The hierarchy is shallow on purpose. Callers branch on maybe three of these --
retry on :class:`RateLimitError`, prompt for a key on :class:`AuthenticationError`, show the
message for everything else -- and a deeper tree would only be more names to
learn for no extra decision.
"""

from __future__ import annotations


class KortexError(Exception):
    """Base for everything this package raises. Catch this to catch all."""


class APIError(KortexError):
    """The server answered, and the answer was an error."""

    def __init__(
        self,
        message: str,
        *,
        status: int,
        title: str = "",
        detail: str = "",
        body: dict | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.title = title
        self.detail = detail
        self.body = body or {}
        self.retry_after = retry_after
        """Seconds the server asked us to wait, when it said. Only 429/503 set it."""


class AuthenticationError(APIError):
    """401/403 -- missing, expired, or insufficient credentials."""


class NotFoundError(APIError):
    """404."""


class ConflictError(APIError):
    """409 -- most often a slug or email already taken."""


class ValidationError(APIError):
    """400/422 -- rejected before it reached the domain."""


class PlanLimitError(APIError):
    """402 -- the org is at its plan's cap. Not retryable; upgrade or delete."""


class RateLimitError(APIError):
    """429. Retried automatically first; you see it once the retries run out."""


class InternalServerError(APIError):
    """5xx. Also retried before you ever see it."""


class APIConnectionError(KortexError):
    """The request never got an answer -- DNS, TLS, timeout, refused."""


_BY_STATUS: dict[int, type[APIError]] = {
    400: ValidationError,
    401: AuthenticationError,
    402: PlanLimitError,
    403: AuthenticationError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
    429: RateLimitError,
}


def error_for(
    status: int,
    body: dict | None,
    text: str,
    retry_after: float | None = None,
) -> APIError:
    """Map an error response onto the narrowest exception that fits."""
    body = body or {}
    title = str(body.get("title") or "")
    detail = str(body.get("detail") or "")
    message = detail or title or text.strip() or f"HTTP {status}"
    cls = _BY_STATUS.get(status) or (InternalServerError if status >= 500 else APIError)
    return cls(
        message,
        status=status,
        title=title,
        detail=detail,
        body=body,
        retry_after=retry_after,
    )
