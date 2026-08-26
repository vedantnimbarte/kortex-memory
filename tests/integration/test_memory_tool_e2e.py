"""Claude's memory tool, end to end against a Kortex scope.

The acceptance path for #26: the six commands behave the way Anthropic's
contract says, and the files they create are ordinary Kortex memories rather
than a parallel store — searchable, exportable, governed.

The last two tests are the point of the whole work unit. Anyone can back the
memory tool with a dict. What a local filesystem cannot do is hold a write for
human review and *tell the model it did*, or leave a deleted file recoverable.
If those two stop working, this is just a slower `os.path`.
"""

from __future__ import annotations

import pytest
from kortex_core.db.types import MemoryKind, ReviewMode, ScopeType, Sensitivity
from kortex_core.memory_tool import PATH_KEY, MemoryToolBackend
from kortex_core.repositories.memory_repo import MemoryRepository, ScopeFilter
from kortex_core.repositories.project_repo import ProjectRepository
from kortex_core.services.auth_service import AuthService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.signup_service import SignupService

pytestmark = pytest.mark.integration

NOTES = "Ledger decisions\n- Postgres over DynamoDB\n- we need joins\n"


async def _backend(session, email: str, org: str):  # type: ignore[no-untyped-def]
    """An owner, their default project, and a backend bound to it."""
    registered = await SignupService(session).register(
        email=email, password="hunter2pass", org_name=org
    )
    principal = (await AuthService(session).principal_from_jwt(registered.access_token)).principal
    scope = next(s for s in principal.roles if s.type == ScopeType.PROJECT)
    backend = MemoryToolBackend(session, principal, scope_type=ScopeType.PROJECT, scope_id=scope.id)
    return backend, principal, scope.id


# --- the six commands -------------------------------------------------------


async def test_create_then_view_round_trips_with_line_numbers(session) -> None:  # type: ignore[no-untyped-def]
    backend, _, _ = await _backend(session, "mt1@acme.io", "Memory Tool Co")

    created = await backend.execute(
        {"command": "create", "path": "/memories/notes.md", "file_text": NOTES}
    )
    await session.flush()
    assert created.content == "File created successfully at: /memories/notes.md"
    assert created.is_error is False

    viewed = await backend.execute({"command": "view", "path": "/memories/notes.md"})
    assert viewed.content.startswith(
        "Here's the content of /memories/notes.md with line numbers:\n     1\tLedger decisions"
    )


async def test_viewing_the_root_lists_what_is_there(session) -> None:  # type: ignore[no-untyped-def]
    backend, _, _ = await _backend(session, "mt2@acme.io", "Memory Tool Two")
    for name in ("a.md", "b.md"):
        await backend.execute({"command": "create", "path": f"/memories/{name}", "file_text": "x"})
    await session.flush()

    listing = await backend.execute({"command": "view", "path": "/memories"})
    assert "up to 2 levels deep in /memories" in listing.content
    assert "/memories/a.md" in listing.content
    assert "/memories/b.md" in listing.content


async def test_an_empty_store_lists_rather_than_erroring(session) -> None:  # type: ignore[no-untyped-def]
    """Claude views its memory directory before doing anything else. An error
    on the first call reads as "your memory is broken"."""
    backend, _, _ = await _backend(session, "mt3@acme.io", "Memory Tool Three")

    listing = await backend.execute({"command": "view", "path": "/memories"})
    assert listing.is_error is False
    assert "/memories" in listing.content


async def test_str_replace_edits_in_place(session) -> None:  # type: ignore[no-untyped-def]
    backend, principal, scope_id = await _backend(session, "mt4@acme.io", "Memory Tool Four")
    await backend.execute({"command": "create", "path": "/memories/notes.md", "file_text": NOTES})
    await session.flush()

    edited = await backend.execute(
        {
            "command": "str_replace",
            "path": "/memories/notes.md",
            "old_str": "Postgres over DynamoDB",
            "new_str": "Postgres over Aurora",
        }
    )
    await session.flush()
    assert edited.content.startswith("The memory file has been edited.")

    # One row, edited -- not a second row shadowing the first.
    repo = MemoryRepository(session, principal=principal)
    rows = await repo.list_by_metadata_key(
        scope_type=ScopeType.PROJECT, scope_id=scope_id, key=PATH_KEY
    )
    assert len(rows) == 1
    assert "Aurora" in rows[0].body


async def test_str_replace_refuses_an_ambiguous_match(session) -> None:  # type: ignore[no-untyped-def]
    """Replacing the first of several silently edits the wrong line as often as
    the right one."""
    backend, _, _ = await _backend(session, "mt5@acme.io", "Memory Tool Five")
    await backend.execute(
        {"command": "create", "path": "/memories/n.md", "file_text": "todo\ntodo\n"}
    )
    await session.flush()

    result = await backend.execute(
        {"command": "str_replace", "path": "/memories/n.md", "old_str": "todo", "new_str": "done"}
    )
    assert result.is_error
    assert "Multiple occurrences" in result.content
    assert "lines: 1, 2" in result.content


async def test_insert_places_text_after_the_named_line(session) -> None:  # type: ignore[no-untyped-def]
    backend, _, _ = await _backend(session, "mt6@acme.io", "Memory Tool Six")
    await backend.execute(
        {"command": "create", "path": "/memories/n.md", "file_text": "one\nthree"}
    )
    await session.flush()

    inserted = await backend.execute(
        {"command": "insert", "path": "/memories/n.md", "insert_line": 1, "insert_text": "two\n"}
    )
    await session.flush()
    assert inserted.content == "The file /memories/n.md has been edited."

    viewed = await backend.execute({"command": "view", "path": "/memories/n.md"})
    assert "     2\ttwo" in viewed.content


async def test_insert_past_the_end_names_the_valid_range(session) -> None:  # type: ignore[no-untyped-def]
    backend, _, _ = await _backend(session, "mt7@acme.io", "Memory Tool Seven")
    await backend.execute({"command": "create", "path": "/memories/n.md", "file_text": "one"})
    await session.flush()

    result = await backend.execute(
        {"command": "insert", "path": "/memories/n.md", "insert_line": 9, "insert_text": "x"}
    )
    assert result.is_error
    assert "[0, 1]" in result.content


async def test_rename_moves_the_file_and_refuses_to_clobber(session) -> None:  # type: ignore[no-untyped-def]
    backend, _, _ = await _backend(session, "mt8@acme.io", "Memory Tool Eight")
    await backend.execute({"command": "create", "path": "/memories/a.md", "file_text": "A"})
    await backend.execute({"command": "create", "path": "/memories/b.md", "file_text": "B"})
    await session.flush()

    moved = await backend.execute(
        {"command": "rename", "old_path": "/memories/a.md", "new_path": "/memories/c.md"}
    )
    await session.flush()
    assert moved.content == "Successfully renamed /memories/a.md to /memories/c.md"
    assert (await backend.execute({"command": "view", "path": "/memories/c.md"})).is_error is False

    clash = await backend.execute(
        {"command": "rename", "old_path": "/memories/c.md", "new_path": "/memories/b.md"}
    )
    assert clash.is_error
    assert "already exists" in clash.content


async def test_the_memory_root_cannot_be_deleted_or_renamed(session) -> None:  # type: ignore[no-untyped-def]
    """Claude's tool description tells it so; the backend should not depend on
    the model having believed it."""
    backend, _, _ = await _backend(session, "mt9@acme.io", "Memory Tool Nine")

    assert (await backend.execute({"command": "delete", "path": "/memories"})).is_error
    assert (
        await backend.execute(
            {"command": "rename", "old_path": "/memories", "new_path": "/memories/x"}
        )
    ).is_error


async def test_a_path_outside_the_root_is_refused(session) -> None:  # type: ignore[no-untyped-def]
    backend, _, _ = await _backend(session, "mt10@acme.io", "Memory Tool Ten")

    result = await backend.execute({"command": "create", "path": "/etc/passwd", "file_text": "x"})
    assert result.is_error
    assert "/memories" in result.content


async def test_an_unknown_command_is_reported_not_raised(session) -> None:  # type: ignore[no-untyped-def]
    """Claude reads the error and corrects itself. It cannot do that with a 500."""
    backend, _, _ = await _backend(session, "mt11@acme.io", "Memory Tool Eleven")

    result = await backend.execute({"command": "chmod", "path": "/memories/x"})
    assert result.is_error
    assert "unknown command" in result.content


# --- what a filesystem cannot do -------------------------------------------


async def test_memory_tool_files_are_ordinary_searchable_memories(session) -> None:  # type: ignore[no-untyped-def]
    """The whole argument for this over a local directory: what Claude wrote
    through the native tool is retrievable through every other surface."""
    backend, principal, scope_id = await _backend(session, "mt12@acme.io", "Memory Tool Twelve")
    await backend.execute({"command": "create", "path": "/memories/ledger.md", "file_text": NOTES})
    await session.flush()

    hits = await MemoryRepository(session, principal=principal).hybrid_search(
        query="DynamoDB",
        query_vector=None,
        scopes=[ScopeFilter(scope_type=ScopeType.PROJECT, scope_id=scope_id)],
        max_sensitivity=Sensitivity.INTERNAL,
    )
    assert [h.title for h in hits] == ["/memories/ledger.md"]


async def test_a_high_sensitivity_recall_does_not_draw_on_them(session) -> None:  # type: ignore[no-untyped-def]
    """Memory-tool files are written as ``tool_output``, which is low trust, so
    a recall at confidential or secret leaves them out.

    Deliberate, and the safer default of the two available. The content is
    model-authored and may contain whatever the session read; it is also re-read
    by the model every session by design, which is exactly the
    injection-persistence shape the trust policy exists for. Low trust is also
    what makes injection quarantine run on these writes at all.

    The cost is stated here rather than discovered: an agent working at
    confidential does not see what Claude wrote through its native tool.
    """
    backend, principal, scope_id = await _backend(session, "mt17@acme.io", "Memory Tool Seventeen")
    await backend.execute({"command": "create", "path": "/memories/ledger.md", "file_text": NOTES})
    await session.flush()

    hits = await MemoryRepository(session, principal=principal).hybrid_search(
        query="DynamoDB",
        query_vector=None,
        scopes=[ScopeFilter(scope_type=ScopeType.PROJECT, scope_id=scope_id)],
        max_sensitivity=Sensitivity.SECRET,
    )
    assert hits == []


async def test_a_gated_write_says_it_was_held(session) -> None:  # type: ignore[no-untyped-def]
    """A bare "created" would tell Claude it had saved something readable when
    it had not, and the next session would find the file missing with nothing to
    explain why."""
    backend, principal, scope_id = await _backend(session, "mt13@acme.io", "Memory Tool Thirteen")
    project = await ProjectRepository(session, principal=principal).get_by_id(scope_id)
    assert project is not None
    project.review_mode = ReviewMode.ALL.value
    await session.flush()

    created = await backend.execute(
        {"command": "create", "path": "/memories/held.md", "file_text": NOTES}
    )
    await session.flush()
    assert "held for human review" in created.content

    # And the content does not come back out until a human approves it.
    viewed = await backend.execute({"command": "view", "path": "/memories/held.md"})
    assert "held for human review" in viewed.content
    assert "Postgres" not in viewed.content


async def test_a_held_file_still_occupies_its_path(session) -> None:  # type: ignore[no-untyped-def]
    """If pending files did not count for identity, create would report success
    and quietly mint a second row at the same address."""
    backend, principal, scope_id = await _backend(session, "mt14@acme.io", "Memory Tool Fourteen")
    project = await ProjectRepository(session, principal=principal).get_by_id(scope_id)
    assert project is not None
    project.review_mode = ReviewMode.ALL.value
    await session.flush()

    await backend.execute({"command": "create", "path": "/memories/h.md", "file_text": "first"})
    await session.flush()
    await backend.execute({"command": "create", "path": "/memories/h.md", "file_text": "second"})
    await session.flush()

    rows = await MemoryRepository(session, principal=principal).list_by_metadata_key(
        scope_type=ScopeType.PROJECT, scope_id=scope_id, key=PATH_KEY
    )
    assert len(rows) == 1


async def test_delete_is_recoverable(session) -> None:  # type: ignore[no-untyped-def]
    """Retrieval stops; the row survives for export and audit. "The agent
    deleted it" is something a compliance reviewer has to be able to see."""
    backend, principal, scope_id = await _backend(session, "mt15@acme.io", "Memory Tool Fifteen")
    await backend.execute({"command": "create", "path": "/memories/d.md", "file_text": NOTES})
    await session.flush()

    removed = await backend.execute({"command": "delete", "path": "/memories/d.md"})
    await session.flush()
    assert removed.content == "Successfully deleted /memories/d.md"
    assert (await backend.execute({"command": "view", "path": "/memories/d.md"})).is_error

    repo = MemoryRepository(session, principal=principal)
    live = await repo.list_by_metadata_key(
        scope_type=ScopeType.PROJECT, scope_id=scope_id, key=PATH_KEY
    )
    assert live == []
    assert await _soft_deleted_count(session, scope_id) == 1


async def test_memory_tool_files_live_beside_ordinary_memories(session) -> None:  # type: ignore[no-untyped-def]
    """One scope, one corpus. A memory an agent wrote through MCP and one Claude
    wrote through its native tool are the same kind of thing."""
    backend, principal, scope_id = await _backend(session, "mt16@acme.io", "Memory Tool Sixteen")
    await MemoryService(session, principal).write(
        CreateMemoryInput(
            scope_type=ScopeType.PROJECT,
            scope_id=scope_id,
            title="written via MCP",
            body="The queue runs on Redis.",
            kind=MemoryKind.FACT,
        )
    )
    await backend.execute({"command": "create", "path": "/memories/n.md", "file_text": NOTES})
    await session.flush()

    listed = await MemoryRepository(session, principal=principal).list_(
        scope=ScopeFilter(scope_type=ScopeType.PROJECT, scope_id=scope_id)
    )
    assert {m.title for m in listed} >= {"written via MCP", "/memories/n.md"}


async def _soft_deleted_count(session, scope_id: int) -> int:  # type: ignore[no-untyped-def]
    from kortex_core.models.memory import Memory
    from sqlalchemy import func, select

    stmt = (
        select(func.count())
        .select_from(Memory)
        .where(
            Memory.scope_id == scope_id,
            Memory.scope_type == ScopeType.PROJECT.value,
            Memory.deleted_at.isnot(None),
        )
    )
    return int((await session.execute(stmt)).scalar_one())
