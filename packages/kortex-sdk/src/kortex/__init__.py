"""Kortex Memory -- Python client.

    from kortex import Kortex

    kx = Kortex(scope=("project", 7))            # reads KORTEX_API_KEY / KORTEX_API_URL
    kx.remember("We chose Postgres over DynamoDB for the ledger: we need joins.")

    for hit in kx.search("which database for the ledger"):
        print(hit.score, hit.title)

Async is the same surface, awaited::

    from kortex import AsyncKortex

    async with AsyncKortex(scope=("project", 7)) as kx:
        bundle = await kx.recall("what did we decide about the ledger")
        prompt = bundle.as_prompt()
"""

from __future__ import annotations

from kortex.client import AsyncKortex, Kortex, Scope, __version__
from kortex.errors import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    ConflictError,
    InternalServerError,
    KortexError,
    NotFoundError,
    PlanLimitError,
    RateLimitError,
    ValidationError,
)
from kortex.models import (
    Citation,
    ConflictNote,
    Memory,
    MemoryToolResult,
    Recall,
    SearchHit,
    SearchResult,
    Tokens,
    Usage,
)

__all__ = [
    "APIConnectionError",
    "APIError",
    "AsyncKortex",
    "AuthenticationError",
    "Citation",
    "ConflictError",
    "ConflictNote",
    "InternalServerError",
    "Kortex",
    "KortexError",
    "Memory",
    "MemoryToolResult",
    "NotFoundError",
    "PlanLimitError",
    "RateLimitError",
    "Recall",
    "Scope",
    "SearchHit",
    "SearchResult",
    "Tokens",
    "Usage",
    "ValidationError",
    "__version__",
]
