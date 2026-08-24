"""Integration: the embedding queue's failure state, against a real database.

The unit tests cover the retry *rule*; these cover the parts only Postgres can
answer — that the pending query actually excludes parked and backed-off rows,
that the status aggregate is org-scoped, and that a requeue releases exactly
what it should.
"""

from __future__ import annotations

import datetime as dt

import pytest
from kortex_core.db.types import MemoryKind, ScopeType
from kortex_core.repositories.memory_repo import MemoryRepository
from kortex_core.services.auth_service import AuthService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.signup_service import SignupService
from kortex_core.settings import get_settings

pytestmark = pytest.mark.integration


async def _owner(session, email: str, org: str):  # type: ignore[no-untyped-def]
    result = await SignupService(session).register(
        email=email, password="hunter2pass", org_name=org
    )
    return (await AuthService(session).principal_from_jwt(result.access_token)).principal


async def _make(svc, scope_id: int, body: str):  # type: ignore[no-untyped-def]
    return await svc.create(
        CreateMemoryInput(
            scope_type=ScopeType.WORKSPACE,
            scope_id=scope_id,
            body=body,
            kind=MemoryKind.FACT,
        )
    )


async def test_pending_query_skips_parked_and_backed_off(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner(session, "embedq@acme.io", "Embed Q")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)
    s = get_settings()

    ready = await _make(svc, ws.id, "ready to embed")
    backed_off = await _make(svc, ws.id, "waiting on backoff")
    parked = await _make(svc, ws.id, "given up on")

    await repo.record_embed_failure(
        [backed_off.id],
        error="transient provider error",
        max_attempts=s.embed_max_attempts,
        retry_base_seconds=3600,
    )
    # Exhaust the budget in one call by allowing a single attempt.
    failed = await repo.record_embed_failure(
        [parked.id], error="bad input", max_attempts=1, retry_base_seconds=60
    )
    assert failed == 1

    pending_ids = {m.id for m in await repo.list_pending_embedding(limit=50)}
    assert ready.id in pending_ids
    assert backed_off.id not in pending_ids, "backoff window not respected"
    assert parked.id not in pending_ids, "parked memory would be retried forever"


async def test_status_counts_and_requeue(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner(session, "embedstat@acme.io", "Embed Stat")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    a = await _make(svc, ws.id, "one")
    b = await _make(svc, ws.id, "two")
    await repo.set_embedding(
        a.id, [0.1] * get_settings().embedder_dim, get_settings().embedder_model
    )
    await repo.record_embed_failure([b.id], error="boom", max_attempts=1, retry_base_seconds=60)

    counts = await repo.embed_status_counts()
    assert counts.ok == 1
    assert counts.failed == 1
    assert counts.pending == 0

    failures = await repo.list_embed_failures(limit=10)
    assert [m.id for m in failures] == [b.id]
    assert failures[0].embed_error == "boom"
    assert failures[0].embedding_state == "failed"

    assert await repo.reset_embed_failures() == 1
    after = await repo.embed_status_counts()
    assert after.failed == 0
    assert after.pending == 1
    assert b.id in {m.id for m in await repo.list_pending_embedding(limit=50)}


async def test_status_counts_do_not_leak_across_orgs(session) -> None:  # type: ignore[no-untyped-def]
    """A tenant checking their own write path must not see anyone else's."""
    mine = await _owner(session, "mine@acme.io", "Mine Co")
    theirs = await _owner(session, "theirs@acme.io", "Theirs Co")

    for principal in (mine, theirs):
        ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
        svc = MemoryService(session, principal)
        repo = MemoryRepository(session, principal=principal)
        memory = await _make(svc, ws.id, "theirs" if principal is theirs else "mine")
        await repo.record_embed_failure(
            [memory.id], error="boom", max_attempts=1, retry_base_seconds=60
        )

    counts = await MemoryRepository(session, principal=mine).embed_status_counts()
    assert counts.failed == 1, "org filter missing from the status aggregate"


async def test_successful_embed_clears_failure_state(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner(session, "embedclear@acme.io", "Embed Clear")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)
    s = get_settings()

    memory = await _make(svc, ws.id, "recovers eventually")
    await repo.record_embed_failure(
        [memory.id], error="boom", max_attempts=1, retry_base_seconds=60
    )
    await repo.set_embedding(memory.id, [0.1] * s.embedder_dim, s.embedder_model)

    refreshed = await repo.get_by_id(memory.id)
    assert refreshed is not None
    assert refreshed.embedding_state == "ok"
    assert refreshed.embed_attempts == 0
    assert refreshed.embed_error is None
    assert refreshed.embed_failed_at is None
    assert refreshed.embed_next_attempt_at is None


async def test_oldest_pending_age_is_reported(session) -> None:  # type: ignore[no-untyped-def]
    """The signal `kortex doctor` and KortexEmbedStalled key off."""
    principal = await _owner(session, "embedage@acme.io", "Embed Age")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    before = dt.datetime.now(tz=dt.UTC)
    await _make(svc, ws.id, "waiting")
    counts = await repo.embed_status_counts()
    assert counts.pending == 1
    elapsed = (dt.datetime.now(tz=dt.UTC) - before).total_seconds()
    assert 0 <= counts.oldest_pending_seconds <= elapsed + 5
