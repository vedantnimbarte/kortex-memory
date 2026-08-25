"""Write-time deduplication, against a real database.

The unit tests pin the fingerprint; these pin that the write path uses it —
that a repeat really does fold into the existing row, and just as importantly
that things which merely resemble each other do not.

The must-not-merge cases matter more than the dedup cases. A missed duplicate
costs a little context; a wrong merge silently discards a memory the caller
believes it stored, and nothing surfaces it.
"""

from __future__ import annotations

import pytest
from kortex_core.db.types import MemoryKind, ScopeType
from kortex_core.repositories.memory_repo import MemoryRepository
from kortex_core.services.auth_service import AuthService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.signup_service import SignupService

pytestmark = pytest.mark.integration

BODY = "The job queue runs on Celery with Redis as the broker."


async def _owner(session, email: str, org: str):  # type: ignore[no-untyped-def]
    result = await SignupService(session).register(
        email=email, password="hunter2pass", org_name=org
    )
    return (await AuthService(session).principal_from_jwt(result.access_token)).principal


def _payload(scope_id: int, body: str = BODY, **over) -> CreateMemoryInput:  # type: ignore[no-untyped-def]
    fields: dict = {
        "scope_type": ScopeType.WORKSPACE,
        "scope_id": scope_id,
        "title": "job queue",
        "body": body,
        "kind": MemoryKind.FACT,
    }
    return CreateMemoryInput(**(fields | over))


async def test_writing_the_same_memory_twice_stores_one_row(session) -> None:  # type: ignore[no-untyped-def]
    """The acceptance case for #18."""
    principal = await _owner(session, "dedup1@acme.io", "Dedup Co")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    first = await svc.write(_payload(ws.id))
    second = await svc.write(_payload(ws.id))
    await session.flush()

    assert first.deduped is False
    assert second.deduped is True
    assert second.memory.id == first.memory.id
    assert await repo.count_for_org(principal.org_id) == 1


async def test_a_repeat_counts_as_an_access(session) -> None:  # type: ignore[no-untyped-def]
    """Re-remembering is evidence the fact still matters, which is what keeps
    it from decaying away."""
    principal = await _owner(session, "dedup2@acme.io", "Dedup Co 2")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)

    first = await svc.write(_payload(ws.id))
    before = first.memory.access_count
    second = await svc.write(_payload(ws.id))

    assert second.memory.access_count == before + 1
    assert second.memory.last_accessed_at is not None


async def test_reformatted_content_is_still_a_duplicate(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner(session, "dedup3@acme.io", "Dedup Co 3")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    await svc.write(_payload(ws.id, body=BODY))
    result = await svc.write(_payload(ws.id, body=f"  {BODY.replace(' ', '  ')}  "))
    await session.flush()

    assert result.deduped is True
    assert await repo.count_for_org(principal.org_id) == 1


async def test_duplicate_metadata_is_merged_not_dropped(session) -> None:  # type: ignore[no-untyped-def]
    """The repeat may carry provenance worth keeping, and the survivor's own
    keys must not be lost to it."""
    principal = await _owner(session, "dedup4@acme.io", "Dedup Co 4")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)

    await svc.write(_payload(ws.id, metadata={"seen_in": "session-1", "keep": "me"}))
    result = await svc.write(_payload(ws.id, metadata={"seen_in": "session-2"}))

    assert result.memory.metadata_["keep"] == "me"
    assert result.memory.metadata_["seen_in"] == "session-2"


# --- the cases that must NOT merge ---


async def test_different_body_is_a_different_memory(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner(session, "dedup5@acme.io", "Dedup Co 5")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    await svc.write(_payload(ws.id, body="The queue runs on Redis."))
    result = await svc.write(_payload(ws.id, body="The queue runs on Postgres."))
    await session.flush()

    assert result.deduped is False
    assert await repo.count_for_org(principal.org_id) == 2


async def test_the_same_text_in_another_scope_is_a_different_memory(session) -> None:  # type: ignore[no-untyped-def]
    """Folding across scopes would leak one project's context into another's
    recall — the whole point of scoping."""
    principal = await _owner(session, "dedup6@acme.io", "Dedup Co 6")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    await svc.write(_payload(ws.id))
    result = await svc.write(_payload(ws.id, scope_type=ScopeType.ORG, scope_id=principal.org_id))
    await session.flush()

    assert result.deduped is False
    assert await repo.count_for_org(principal.org_id) == 2


async def test_force_stores_a_second_copy(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner(session, "dedup7@acme.io", "Dedup Co 7")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    first = await svc.write(_payload(ws.id))
    forced = await svc.write(_payload(ws.id), force=True)
    await session.flush()

    assert forced.deduped is False
    assert forced.memory.id != first.memory.id
    assert await repo.count_for_org(principal.org_id) == 2


async def test_a_forced_copy_still_becomes_a_dedup_target(session) -> None:  # type: ignore[no-untyped-def]
    """A forced write records its fingerprint, so the next unforced write folds
    into the original rather than adding a third row."""
    principal = await _owner(session, "dedup8@acme.io", "Dedup Co 8")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    await svc.write(_payload(ws.id))
    await svc.write(_payload(ws.id), force=True)
    third = await svc.write(_payload(ws.id))
    await session.flush()

    assert third.deduped is True
    assert await repo.count_for_org(principal.org_id) == 2


async def test_a_deleted_memory_can_be_written_again(session) -> None:  # type: ignore[no-untyped-def]
    """Dedup must not resurrect something the caller deliberately removed."""
    principal = await _owner(session, "dedup9@acme.io", "Dedup Co 9")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)

    first = await svc.write(_payload(ws.id))
    await session.flush()
    assert await svc.delete(first.memory.public_id) is True
    await session.flush()

    again = await svc.write(_payload(ws.id))
    assert again.deduped is False
    assert again.memory.id != first.memory.id


async def test_a_duplicate_does_not_consume_plan_quota(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Folding a repeat stores nothing new, so it must not push an org over its
    cap — otherwise a retrying client can exhaust a plan without adding data."""
    from kortex_core.security import plan_limits

    monkeypatch.setitem(
        plan_limits.PLAN_LIMITS,
        "free",
        plan_limits.PlanLimits(max_memories=1, max_workspaces=1),
    )
    principal = await _owner(session, "dedup10@acme.io", "Dedup Co 10")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)

    await svc.write(_payload(ws.id))
    await session.flush()
    # At the cap. A genuine second memory would be rejected; a repeat must not be.
    result = await svc.write(_payload(ws.id))
    assert result.deduped is True


async def test_dedup_can_be_turned_off(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from kortex_core.settings import get_settings

    monkeypatch.setattr(get_settings(), "dedup_on_write", False, raising=False)
    principal = await _owner(session, "dedup11@acme.io", "Dedup Co 11")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    repo = MemoryRepository(session, principal=principal)

    await svc.write(_payload(ws.id))
    result = await svc.write(_payload(ws.id))
    await session.flush()

    assert result.deduped is False
    assert await repo.count_for_org(principal.org_id) == 2


async def test_create_still_returns_the_memory(session) -> None:  # type: ignore[no-untyped-def]
    """`create` keeps its old signature, so existing callers are unaffected."""
    principal = await _owner(session, "dedup12@acme.io", "Dedup Co 12")
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)

    memory = await svc.create(_payload(ws.id))
    again = await svc.create(_payload(ws.id))
    assert again.id == memory.id
