"""One request, sent properly.

Sync and async differ in exactly two places -- how they send, and how they
sleep. Everything that could be got wrong (which failures are worth retrying,
how long to wait, whose advice to take, what to raise) is pure and lives here
once, so the two clients cannot drift apart on the interesting half.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from typing import Any

import httpx

from kortex.errors import APIConnectionError, error_for

DEFAULT_BASE_URL = "http://localhost:8000"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
"""No 4xx but 429: retrying a rejected request just gets it rejected again."""


@dataclass(frozen=True, slots=True)
class Request:
    method: str
    path: str
    json: dict[str, Any] | None = None
    params: dict[str, Any] | None = None


def resolve_base_url(base_url: str | None) -> str:
    return (base_url or os.environ.get("KORTEX_API_URL") or DEFAULT_BASE_URL).rstrip("/")


def build_headers(api_key: str | None, token: str | None, user_agent: str) -> dict[str, str]:
    """Credentials in, headers out.

    An explicit key beats a JWT beats the environment. API keys go in
    ``X-API-Key`` rather than ``Authorization`` because the rate limiter buckets
    on the key prefix and only reads that header.
    """
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    key = api_key or os.environ.get("KORTEX_API_KEY")
    if key:
        headers["X-API-Key"] = key
    elif token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def retry_delay(response: httpx.Response | None, attempt: int, backoff: float) -> float:
    """How long to wait before attempt ``attempt`` (1-based), in seconds.

    The server's ``Retry-After`` wins when it sent one -- it knows when the
    rate-limit window rolls over and we are guessing. Otherwise exponential
    with jitter, because a fleet of clients backing off in lockstep just
    reconverges on the same instant.
    """
    if response is not None:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return max(0.0, float(header))
            except ValueError:
                pass  # http-date form; fall through to our own backoff
    # 2.0 rather than 2: typeshed widens int**int to Any, since a negative
    # exponent would give a float.
    return backoff * (2.0 ** (attempt - 1)) * (0.5 + random.random())  # noqa: S311


def should_retry(response: httpx.Response | None, attempt: int, max_retries: int) -> bool:
    if attempt > max_retries:
        return False
    return response is None or response.status_code in RETRY_STATUSES


def parse(response: httpx.Response) -> Any:
    """Return the decoded body, or raise the error it describes."""
    body: Any = None
    if response.content:
        try:
            body = response.json()
        except ValueError:
            body = None

    if response.is_success:
        return body

    header = response.headers.get("Retry-After")
    retry_after: float | None = None
    if header:
        try:
            retry_after = float(header)
        except ValueError:
            retry_after = None
    raise error_for(
        response.status_code,
        body if isinstance(body, dict) else None,
        response.text,
        retry_after,
    )


def wrap_transport_error(exc: httpx.HTTPError) -> APIConnectionError:
    return APIConnectionError(f"could not reach the Kortex API: {exc}")
