"""The client. Two of them -- one sync, one async, same surface.

The verbs match the ones the MCP tools already use (``remember``, ``search``,
``recall``, ``forget``), because an integrator who has seen Kortex through
Claude Code should not have to learn a second vocabulary for the same
operations.

Only the calls an integrator actually makes are typed here. The other fifty-odd
endpoints -- billing, admin, tenancy, attachments -- stay reachable through
:meth:`Kortex.request` rather than being hand-wrapped, because a method that
exists only so the surface looks complete is a method someone has to keep in
step with the server for no one's benefit.

Each request is built once, by a plain function, and sent by whichever client
you are holding. That is what keeps the sync and async versions honestly
identical instead of nearly identical.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from collections.abc import Sequence
from typing import Any

import httpx

from kortex import _transport as t
from kortex.models import Memory, Recall, SearchResult, Tokens

__version__ = "0.1.0"
USER_AGENT = f"kortex-python/{__version__}"

Scope = tuple[str, int]
"""A scope filter: ``("project", 7)``. Types are ``org``/``workspace``/``project``/``session``."""


def _scopes(scopes: Sequence[Scope] | None) -> list[dict[str, Any]] | None:
    if not scopes:
        return None
    return [{"scope_type": st, "scope_id": sid} for st, sid in scopes]


def _drop_none(d: dict[str, Any]) -> dict[str, Any]:
    """Omit unset options so the server's own defaults apply.

    Sending ``null`` for a field with a non-null default overrides that default
    with a validation error, which is a confusing way to learn you left an
    argument out.
    """
    return {k: v for k, v in d.items() if v is not None}


# --- request builders -------------------------------------------------------


def _remember(
    body: str,
    scope: Scope,
    *,
    title: str,
    kind: str | None,
    sensitivity: str | None,
    importance: float | None,
    pinned: bool,
    metadata: dict[str, Any] | None,
    confidence: float | None,
    expires_at: dt.datetime | None,
    source_type: str | None,
    embed_inline: bool,
    force: bool,
) -> t.Request:
    payload = _drop_none(
        {
            "scope_type": scope[0],
            "scope_id": scope[1],
            "body": body,
            "title": title,
            "kind": kind,
            "sensitivity": sensitivity,
            "source_type": source_type,
            "importance": importance,
            "pinned": pinned,
            "metadata": metadata,
            "confidence": confidence,
            "expires_at": expires_at.isoformat() if expires_at else None,
        }
    )
    return t.Request(
        "POST",
        "/v1/memories",
        json=payload,
        params={"embed_inline": embed_inline, "force": force},
    )


def _search(
    query: str,
    scopes: Sequence[Scope] | None,
    limit: int,
    embed_query: bool,
) -> t.Request:
    return t.Request(
        "POST",
        "/v1/search",
        json=_drop_none(
            {
                "query": query,
                "scopes": _scopes(scopes),
                "limit": limit,
                "embed_query": embed_query,
            }
        ),
    )


def _recall(
    query: str,
    scopes: Sequence[Scope] | None,
    *,
    synthesize: bool,
    max_tokens: int,
    per_item_max: int,
    latency_budget_ms: int,
    token_budget: int,
) -> t.Request:
    return t.Request(
        "POST",
        "/v1/search/recall",
        json=_drop_none(
            {
                "query": query,
                "scopes": _scopes(scopes),
                "synthesize": synthesize,
                "max_tokens": max_tokens,
                "per_item_max": per_item_max,
                "latency_budget_ms": latency_budget_ms,
                "token_budget": token_budget,
            }
        ),
    )


def _list(
    scope: Scope | None,
    *,
    tier: str | None,
    kind: str | None,
    limit: int,
    offset: int,
) -> t.Request:
    params = _drop_none(
        {
            "scope_type": scope[0] if scope else None,
            "scope_id": scope[1] if scope else None,
            "tier": tier,
            "kind": kind,
            "limit": limit,
            "offset": offset,
        }
    )
    return t.Request("GET", "/v1/memories", params=params)


def _update(
    memory_id: str,
    *,
    title: str | None,
    body: str | None,
    kind: str | None,
    sensitivity: str | None,
    importance: float | None,
    metadata: dict[str, Any] | None,
) -> t.Request:
    return t.Request(
        "PATCH",
        f"/v1/memories/{memory_id}",
        json=_drop_none(
            {
                "title": title,
                "body": body,
                "kind": kind,
                "sensitivity": sensitivity,
                "importance": importance,
                "metadata": metadata,
            }
        ),
    )


# --- shared construction ----------------------------------------------------


class _Base:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        token: str | None = None,
        scope: Scope | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: float = 0.5,
    ):
        """
        ``api_key`` falls back to ``KORTEX_API_KEY`` and ``base_url`` to
        ``KORTEX_API_URL``, so a configured environment needs ``Kortex()``.

        ``scope`` is the default every call uses when you do not name one --
        set it once at construction rather than repeating ``("project", 7)``
        at fifty call sites.
        """
        self._base_url = t.resolve_base_url(base_url)
        self._headers = t.build_headers(api_key, token, USER_AGENT)
        self._scope = scope
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff = backoff

    def _resolve(self, scope: Scope | None) -> Scope:
        chosen = scope or self._scope
        if chosen is None:
            raise ValueError(
                "no scope given and no default set: pass scope=('project', <id>) "
                "here, or Kortex(..., scope=('project', <id>)) once"
            )
        return chosen

    def set_token(self, token: str) -> None:
        """Authenticate as a user from here on, after :meth:`login` or
        :meth:`register`. Replaces an API key rather than sitting beside it:
        two credentials on one request is a question the server should not have
        to answer."""
        self._headers.pop("X-API-Key", None)
        self._headers["Authorization"] = f"Bearer {token}"


class Kortex(_Base):
    """Blocking client.

        >>> kx = Kortex(scope=("project", 7))
        >>> kx.remember("We settled on Postgres over DynamoDB for the ledger.")
        >>> kx.search("what database for the ledger").hits[0].body

    Safe to keep for the life of the process; it holds a pooled connection.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        token: str | None = None,
        scope: Scope | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: float = 0.5,
    ):
        super().__init__(
            api_key,
            base_url=base_url,
            token=token,
            scope=scope,
            timeout=timeout,
            max_retries=max_retries,
            backoff=backoff,
        )
        # Headers ride on each request rather than the client, so set_token is
        # a dict write and cannot leave a stale credential on a pooled client.
        self._client = httpx.Client(base_url=self._base_url, timeout=self._timeout)

    # -- plumbing --
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Kortex:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _send(self, req: t.Request) -> Any:
        attempt = 0
        while True:
            attempt += 1
            response: httpx.Response | None = None
            try:
                response = self._client.request(
                    req.method,
                    req.path,
                    json=req.json,
                    params=req.params,
                    headers=self._headers,
                )
                if not t.should_retry(response, attempt, self._max_retries):
                    return t.parse(response)
            except httpx.HTTPError as exc:
                if not t.should_retry(None, attempt, self._max_retries):
                    raise t.wrap_transport_error(exc) from exc
            time.sleep(t.retry_delay(response, attempt, self._backoff))

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Any endpoint, decoded but untyped -- the escape hatch for the
        long tail this client does not wrap."""
        return self._send(t.Request(method.upper(), path, json=json, params=params))

    # -- auth --
    def register(self, email: str, password: str, org_name: str) -> Tokens:
        """Create an org and its first user, then authenticate as them."""
        tokens = Tokens._from(
            self._send(
                t.Request(
                    "POST",
                    "/v1/auth/register",
                    json={"email": email, "password": password, "org_name": org_name},
                )
            )
        )
        self.set_token(tokens.access_token)
        return tokens

    def login(self, email: str, password: str) -> Tokens:
        tokens = Tokens._from(
            self._send(
                t.Request("POST", "/v1/auth/login", json={"email": email, "password": password})
            )
        )
        self.set_token(tokens.access_token)
        return tokens

    def whoami(self) -> dict[str, Any]:
        result: dict[str, Any] = self._send(t.Request("GET", "/v1/auth/whoami"))
        return result

    # -- memories --
    def remember(
        self,
        body: str,
        *,
        scope: Scope | None = None,
        title: str = "",
        kind: str | None = None,
        sensitivity: str | None = None,
        importance: float | None = None,
        pinned: bool = False,
        metadata: dict[str, Any] | None = None,
        confidence: float | None = None,
        expires_at: dt.datetime | None = None,
        source_type: str | None = None,
        embed_inline: bool = False,
        force: bool = False,
    ) -> Memory:
        """Store a memory.

        Writing the same text twice folds into the existing memory rather than
        storing a rival copy -- check ``.deduped`` if you need to know which
        happened, or pass ``force=True`` to insist.

        ``embed_inline`` waits for the vector instead of queueing it: slower,
        but the memory is in semantic search the moment this returns.
        """
        return Memory._from(
            self._send(
                _remember(
                    body,
                    self._resolve(scope),
                    title=title,
                    kind=kind,
                    sensitivity=sensitivity,
                    importance=importance,
                    pinned=pinned,
                    metadata=metadata,
                    confidence=confidence,
                    expires_at=expires_at,
                    source_type=source_type,
                    embed_inline=embed_inline,
                    force=force,
                )
            )
        )

    def search(
        self,
        query: str,
        *,
        scopes: Sequence[Scope] | None = None,
        limit: int = 20,
        embed_query: bool = True,
    ) -> SearchResult:
        """Hybrid retrieval: vectors and keywords, fused, decay-weighted.

        Check ``.used_vector`` -- ``False`` means the embedder was unavailable
        and this degraded to keyword-only rather than failing.
        """
        return SearchResult._from(
            self._send(_search(query, scopes or self._scope_list(), limit, embed_query))
        )

    def recall(
        self,
        query: str,
        *,
        scopes: Sequence[Scope] | None = None,
        synthesize: bool = False,
        max_tokens: int = 0,
        per_item_max: int = 800,
        latency_budget_ms: int = 0,
        token_budget: int = 0,
    ) -> Recall:
        """Agentic retrieval: the server plans, searches, and re-ranks.

        Costs LLM tokens where :meth:`search` does not. ``max_tokens`` caps the
        context returned, ``token_budget`` and ``latency_budget_ms`` cap the
        planning itself -- a budget too small to plan in degrades to plain
        hybrid rather than overshooting.
        """
        return Recall._from(
            self._send(
                _recall(
                    query,
                    scopes or self._scope_list(),
                    synthesize=synthesize,
                    max_tokens=max_tokens,
                    per_item_max=per_item_max,
                    latency_budget_ms=latency_budget_ms,
                    token_budget=token_budget,
                )
            )
        )

    def get(self, memory_id: str) -> Memory:
        return Memory._from(self._send(t.Request("GET", f"/v1/memories/{memory_id}")))

    def list_memories(
        self,
        *,
        scope: Scope | None = None,
        tier: str | None = None,
        kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        rows = self._send(
            _list(scope or self._scope, tier=tier, kind=kind, limit=limit, offset=offset)
        )
        return [Memory._from(r) for r in rows or []]

    def update(
        self,
        memory_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        kind: str | None = None,
        sensitivity: str | None = None,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory:
        return Memory._from(
            self._send(
                _update(
                    memory_id,
                    title=title,
                    body=body,
                    kind=kind,
                    sensitivity=sensitivity,
                    importance=importance,
                    metadata=metadata,
                )
            )
        )

    def forget(self, memory_id: str) -> None:
        """Soft-delete. The row survives for export and audit; retrieval stops."""
        self._send(t.Request("DELETE", f"/v1/memories/{memory_id}"))

    def pin(self, memory_id: str) -> None:
        """Exempt from decay, and floored into every recall that matches it."""
        self._send(t.Request("POST", f"/v1/memories/{memory_id}/pin"))

    def unpin(self, memory_id: str) -> None:
        self._send(t.Request("DELETE", f"/v1/memories/{memory_id}/pin"))

    def bulk(self, action: str, memory_ids: Sequence[str]) -> int:
        """``pin``, ``unpin`` or ``delete`` up to 200 memories. Returns the count."""
        result = self._send(
            t.Request(
                "POST", "/v1/memories/bulk", json={"action": action, "public_ids": list(memory_ids)}
            )
        )
        return int((result or {}).get("affected", 0))

    def _scope_list(self) -> list[Scope] | None:
        return [self._scope] if self._scope else None


class AsyncKortex(_Base):
    """The same client, awaited.

    >>> async with AsyncKortex(scope=("project", 7)) as kx:
    ...     await kx.remember("Rate limits are per API key, not per org.")
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        token: str | None = None,
        scope: Scope | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: float = 0.5,
    ):
        super().__init__(
            api_key,
            base_url=base_url,
            token=token,
            scope=scope,
            timeout=timeout,
            max_retries=max_retries,
            backoff=backoff,
        )
        # Headers ride on each request rather than the client, so set_token is
        # a dict write and cannot leave a stale credential on a pooled client.
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)

    # -- plumbing --
    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncKortex:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _send(self, req: t.Request) -> Any:
        attempt = 0
        while True:
            attempt += 1
            response: httpx.Response | None = None
            try:
                response = await self._client.request(
                    req.method,
                    req.path,
                    json=req.json,
                    params=req.params,
                    headers=self._headers,
                )
                if not t.should_retry(response, attempt, self._max_retries):
                    return t.parse(response)
            except httpx.HTTPError as exc:
                if not t.should_retry(None, attempt, self._max_retries):
                    raise t.wrap_transport_error(exc) from exc
            await asyncio.sleep(t.retry_delay(response, attempt, self._backoff))

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Any endpoint, decoded but untyped."""
        return await self._send(t.Request(method.upper(), path, json=json, params=params))

    # -- auth --
    async def register(self, email: str, password: str, org_name: str) -> Tokens:
        tokens = Tokens._from(
            await self._send(
                t.Request(
                    "POST",
                    "/v1/auth/register",
                    json={"email": email, "password": password, "org_name": org_name},
                )
            )
        )
        self.set_token(tokens.access_token)
        return tokens

    async def login(self, email: str, password: str) -> Tokens:
        tokens = Tokens._from(
            await self._send(
                t.Request("POST", "/v1/auth/login", json={"email": email, "password": password})
            )
        )
        self.set_token(tokens.access_token)
        return tokens

    async def whoami(self) -> dict[str, Any]:
        result: dict[str, Any] = await self._send(t.Request("GET", "/v1/auth/whoami"))
        return result

    # -- memories --
    async def remember(
        self,
        body: str,
        *,
        scope: Scope | None = None,
        title: str = "",
        kind: str | None = None,
        sensitivity: str | None = None,
        importance: float | None = None,
        pinned: bool = False,
        metadata: dict[str, Any] | None = None,
        confidence: float | None = None,
        expires_at: dt.datetime | None = None,
        source_type: str | None = None,
        embed_inline: bool = False,
        force: bool = False,
    ) -> Memory:
        """See :meth:`Kortex.remember`."""
        return Memory._from(
            await self._send(
                _remember(
                    body,
                    self._resolve(scope),
                    title=title,
                    kind=kind,
                    sensitivity=sensitivity,
                    importance=importance,
                    pinned=pinned,
                    metadata=metadata,
                    confidence=confidence,
                    expires_at=expires_at,
                    source_type=source_type,
                    embed_inline=embed_inline,
                    force=force,
                )
            )
        )

    async def search(
        self,
        query: str,
        *,
        scopes: Sequence[Scope] | None = None,
        limit: int = 20,
        embed_query: bool = True,
    ) -> SearchResult:
        """See :meth:`Kortex.search`."""
        return SearchResult._from(
            await self._send(_search(query, scopes or self._scope_list(), limit, embed_query))
        )

    async def recall(
        self,
        query: str,
        *,
        scopes: Sequence[Scope] | None = None,
        synthesize: bool = False,
        max_tokens: int = 0,
        per_item_max: int = 800,
        latency_budget_ms: int = 0,
        token_budget: int = 0,
    ) -> Recall:
        """See :meth:`Kortex.recall`."""
        return Recall._from(
            await self._send(
                _recall(
                    query,
                    scopes or self._scope_list(),
                    synthesize=synthesize,
                    max_tokens=max_tokens,
                    per_item_max=per_item_max,
                    latency_budget_ms=latency_budget_ms,
                    token_budget=token_budget,
                )
            )
        )

    async def get(self, memory_id: str) -> Memory:
        return Memory._from(await self._send(t.Request("GET", f"/v1/memories/{memory_id}")))

    async def list_memories(
        self,
        *,
        scope: Scope | None = None,
        tier: str | None = None,
        kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Memory]:
        rows = await self._send(
            _list(scope or self._scope, tier=tier, kind=kind, limit=limit, offset=offset)
        )
        return [Memory._from(r) for r in rows or []]

    async def update(
        self,
        memory_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        kind: str | None = None,
        sensitivity: str | None = None,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Memory:
        return Memory._from(
            await self._send(
                _update(
                    memory_id,
                    title=title,
                    body=body,
                    kind=kind,
                    sensitivity=sensitivity,
                    importance=importance,
                    metadata=metadata,
                )
            )
        )

    async def forget(self, memory_id: str) -> None:
        await self._send(t.Request("DELETE", f"/v1/memories/{memory_id}"))

    async def pin(self, memory_id: str) -> None:
        await self._send(t.Request("POST", f"/v1/memories/{memory_id}/pin"))

    async def unpin(self, memory_id: str) -> None:
        await self._send(t.Request("DELETE", f"/v1/memories/{memory_id}/pin"))

    async def bulk(self, action: str, memory_ids: Sequence[str]) -> int:
        result = await self._send(
            t.Request(
                "POST", "/v1/memories/bulk", json={"action": action, "public_ids": list(memory_ids)}
            )
        )
        return int((result or {}).get("affected", 0))

    def _scope_list(self) -> list[Scope] | None:
        return [self._scope] if self._scope else None
