"""Claude's native memory tool, backed by Kortex scopes.

Anthropic's ``memory_20250818`` tool is client-side: Claude asks for a file
operation, *your* application performs it, and you hand back the result. The
usual implementation writes to local disk, which gives one user, on one
machine, one tool, with no access control and no audit trail.

This is the same interface backed by a Kortex scope instead. The files become
ordinary memories — governed by the same review gating, PII scanning and trust
policy as every other write, readable by the MCP tools and the REST API and the
console, shared across a team, exportable, and soft-deleted rather than erased.
The native path stops being a competing memory store and becomes a way into
this one.

Two places where the behaviour deliberately differs from a filesystem, both
because a filesystem has no opinions and this does:

* A write held for review reports that it was held. Returning a bare "created"
  would tell Claude it had saved something readable when it had not, and the
  next session would find the file missing with no explanation.
* ``delete`` soft-deletes. Retrieval stops; the row survives for export and
  audit. "The agent deleted it" is a thing a compliance reviewer needs to be
  able to see, not a thing that leaves no trace.

The wire contract is Anthropic's, not ours:
https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import MemoryKind, MemorySource, ScopeType, Sensitivity
from kortex_core.models.memory import Memory
from kortex_core.repositories.memory_repo import MemoryRepository
from kortex_core.security.principal import Principal
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService

MEMORY_ROOT = "/memories"
PATH_KEY = "memory_tool_path"
"""Metadata key that makes a memory addressable as a memory-tool file."""

MAX_LINES = 999_999
"""Anthropic's documented ceiling for a viewable file."""

_TRAVERSAL = re.compile(r"(^|/)\.\.(/|$)")
_ENCODED = re.compile(r"%2e|%2f|%5c", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What goes back in the ``tool_result`` block."""

    content: str
    is_error: bool = False


class _RejectedError(Exception):
    """A command that cannot be attempted. Carries the text Claude should see."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --- paths ------------------------------------------------------------------


def normalise_path(raw: Any) -> str:
    """Validate and canonicalise a memory-tool path.

    Paths here address rows, not files, so ``..`` cannot escape onto a real
    filesystem — but it is still rejected. Two reasons, and the second is the
    one that bites: an unnormalised path lets ``/memories/a/../b`` and
    ``/memories/b`` name the same file under two different keys, so Claude
    writes to one and reads back the other and the memory appears to have been
    lost. Aliasing is a correctness bug before it is a security one.

    Percent-encoded traversal is rejected rather than decoded: nothing legitimate
    sends it, so its presence means someone is probing.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise _RejectedError("Error: a path is required")
    path = raw.strip()
    if _ENCODED.search(path):
        raise _RejectedError(f"Error: The path {path} is not permitted")
    if _TRAVERSAL.search(path) or "\\" in path:
        raise _RejectedError(f"Error: The path {path} is not permitted")

    canonical = posixpath.normpath(path)
    if canonical != MEMORY_ROOT and not canonical.startswith(MEMORY_ROOT + "/"):
        raise _RejectedError(
            f"Error: The path {path} is outside {MEMORY_ROOT}. "
            f"All memory paths must start with {MEMORY_ROOT}/."
        )
    return canonical


def _human_size(text: str) -> str:
    """``4.0K``-style sizes, matching what the reference implementation shows."""
    size = len(text.encode("utf-8"))
    if size < 1024:
        return f"{max(size, 1)}"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}K"
    return f"{size / (1024 * 1024):.1f}M"


def _numbered(body: str, *, first: int = 1) -> str:
    """Six-wide right-aligned line numbers, tab, content. 1-indexed.

    ``first`` keeps the numbering absolute when only a window of the file is
    shown. Renumbering a slice from 1 would be a lie Claude then acts on: its
    next ``insert_line`` would land somewhere else entirely.
    """
    lines = body.split("\n")
    return "\n".join(f"{i:6d}\t{line}" for i, line in enumerate(lines, start=first))


# --- the backend ------------------------------------------------------------


class MemoryToolBackend:
    """Executes one memory-tool command against one Kortex scope."""

    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        scope_type: ScopeType,
        scope_id: int,
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
    ):
        self._session = session
        self._principal = principal
        self._scope_type = scope_type
        self._scope_id = scope_id
        self._sensitivity = sensitivity
        self._repo = MemoryRepository(session, principal=principal)
        self._service = MemoryService(session, principal)

    async def execute(self, command: dict[str, Any]) -> ToolResult:
        """Run one command. Never raises for a bad request — Claude reads the
        error text and corrects itself, which it cannot do with an HTTP 500."""
        name = command.get("command")
        handlers = {
            "view": self._view,
            "create": self._create,
            "str_replace": self._str_replace,
            "insert": self._insert,
            "delete": self._delete,
            "rename": self._rename,
        }
        handler = handlers.get(name if isinstance(name, str) else "")
        if handler is None:
            return ToolResult(f"Error: unknown command {name!r}", is_error=True)
        try:
            return await handler(command)
        except _RejectedError as rejected:
            return ToolResult(rejected.message, is_error=True)

    # -- lookups --

    async def _file(self, path: str) -> Memory | None:
        """The memory addressed by ``path``, held-for-review ones included.

        Pending files count for *identity* even though they are invisible to
        recall. If they did not, ``create`` on a held path would report success
        and quietly mint a second row, and Claude would be told a file it just
        wrote does not exist.
        """
        return await self._repo.find_by_metadata(
            scope_type=self._scope_type,
            scope_id=self._scope_id,
            key=PATH_KEY,
            value=path,
        )

    async def _tree(self) -> list[Memory]:
        return await self._repo.list_by_metadata_key(
            scope_type=self._scope_type,
            scope_id=self._scope_id,
            key=PATH_KEY,
        )

    @staticmethod
    def _path_of(memory: Memory) -> str:
        return str((memory.metadata_ or {}).get(PATH_KEY, ""))

    # -- commands --

    async def _view(self, command: dict[str, Any]) -> ToolResult:
        path = normalise_path(command.get("path"))
        memory = await self._file(path)

        if memory is None:
            listing = await self._listing(path)
            if listing is not None:
                return ToolResult(listing)
            return ToolResult(
                f"The path {path} does not exist. Please provide a valid path.",
                is_error=True,
            )

        if memory.review_status == "pending":
            # Deliberately not the body. A project that gates writes is saying a
            # human reads this before an agent does; handing it straight back to
            # the model would make the gate decorative.
            reason = memory.review_reason or "awaiting review"
            return ToolResult(
                f"The file {path} exists but is held for human review ({reason}) "
                "and cannot be read until it is approved."
            )

        body = memory.body
        if body.count("\n") + 1 > MAX_LINES:
            return ToolResult(
                f"File {path} exceeds maximum line limit of {MAX_LINES:,} lines.",
                is_error=True,
            )

        first = 1
        window = command.get("view_range")
        if isinstance(window, list) and len(window) == 2:
            body, first = _slice(body, window)
        return ToolResult(
            f"Here's the content of {path} with line numbers:\n{_numbered(body, first=first)}"
        )

    async def _listing(self, path: str) -> str | None:
        """A directory view, or ``None`` if nothing lives under ``path``.

        There are no directory rows — a directory exists exactly when something
        is stored beneath it. ``/memories`` itself always exists, so a first
        ``view`` of an empty store returns an empty listing rather than an
        error, which is what the reference implementation does and what stops
        Claude concluding its memory is broken.
        """
        prefix = path.rstrip("/") + "/"
        children = [m for m in await self._tree() if self._path_of(m).startswith(prefix)]
        if not children and path != MEMORY_ROOT:
            return None

        rows = [f"{_human_size(''.join(m.body for m in children))}\t{path}"]
        for memory in sorted(children, key=self._path_of):
            rows.append(f"{_human_size(memory.body)}\t{self._path_of(memory)}")
        return (
            f"Here're the files and directories up to 2 levels deep in {path}, "
            f"excluding hidden items and node_modules:\n" + "\n".join(rows)
        )

    async def _create(self, command: dict[str, Any]) -> ToolResult:
        path = normalise_path(command.get("path"))
        if path == MEMORY_ROOT:
            raise _RejectedError(f"Error: {MEMORY_ROOT} is a directory, not a file")
        text = command.get("file_text")
        if not isinstance(text, str):
            raise _RejectedError("Error: file_text is required for create")

        existing = await self._file(path)
        if existing is not None:
            # Overwrite rather than error. The reference implementation errors,
            # but the tool description Claude was trained against says create
            # "creates or overwrites" — erroring makes it retry with delete then
            # create, which is two more round trips for the same outcome. The
            # previous content is not lost silently: the row keeps its id, its
            # updated_at moves, and the change is visible in the console.
            await self._service.update(existing.public_id, body=text, title=path)
            return ToolResult(f"File created successfully at: {path}")

        return ToolResult(await self._store(path, text, verb="File created successfully at"))

    async def _str_replace(self, command: dict[str, Any]) -> ToolResult:
        path = normalise_path(command.get("path"))
        memory = await self._require_file(path)
        old = command.get("old_str")
        if not isinstance(old, str) or not old:
            raise _RejectedError("Error: old_str is required for str_replace")
        new = command.get("new_str")
        new = new if isinstance(new, str) else ""  # omitting new_str means delete

        occurrences = memory.body.count(old)
        if occurrences == 0:
            return ToolResult(
                f"No replacement was performed, old_str `{old}` did not appear verbatim in {path}.",
                is_error=True,
            )
        if occurrences > 1:
            lines = [
                str(i) for i, line in enumerate(memory.body.split("\n"), start=1) if old in line
            ]
            return ToolResult(
                f"No replacement was performed. Multiple occurrences of old_str `{old}` "
                f"in lines: {', '.join(lines)}. Please ensure it is unique",
                is_error=True,
            )

        updated = memory.body.replace(old, new, 1)
        await self._service.update(memory.public_id, body=updated)
        return ToolResult(f"The memory file has been edited.\n{_numbered(updated)}")

    async def _insert(self, command: dict[str, Any]) -> ToolResult:
        path = normalise_path(command.get("path"))
        memory = await self._require_file(path, missing=f"Error: The path {path} does not exist")
        line_no = command.get("insert_line")
        if not isinstance(line_no, int) or isinstance(line_no, bool):
            raise _RejectedError("Error: insert_line must be an integer")

        lines = memory.body.split("\n")
        if line_no < 0 or line_no > len(lines):
            return ToolResult(
                f"Error: Invalid `insert_line` parameter: {line_no}. It should be within "
                f"the range of lines of the file: [0, {len(lines)}]",
                is_error=True,
            )
        text = command.get("insert_text")
        if not isinstance(text, str):
            raise _RejectedError("Error: insert_text is required for insert")

        lines.insert(line_no, text.rstrip("\n"))
        await self._service.update(memory.public_id, body="\n".join(lines))
        return ToolResult(f"The file {path} has been edited.")

    async def _delete(self, command: dict[str, Any]) -> ToolResult:
        path = normalise_path(command.get("path"))
        if path == MEMORY_ROOT:
            raise _RejectedError(f"Error: {MEMORY_ROOT} cannot be deleted")

        memory = await self._file(path)
        if memory is not None:
            await self._service.delete(memory.public_id)
            return ToolResult(f"Successfully deleted {path}")

        # A directory: delete everything beneath it, as the reference does.
        prefix = path.rstrip("/") + "/"
        children = [m for m in await self._tree() if self._path_of(m).startswith(prefix)]
        if not children:
            return ToolResult(f"Error: The path {path} does not exist", is_error=True)
        for child in children:
            await self._service.delete(child.public_id)
        return ToolResult(f"Successfully deleted {path}")

    async def _rename(self, command: dict[str, Any]) -> ToolResult:
        old_path = normalise_path(command.get("old_path"))
        new_path = normalise_path(command.get("new_path"))
        if old_path == MEMORY_ROOT:
            raise _RejectedError(f"Error: {MEMORY_ROOT} cannot be renamed")

        memory = await self._file(old_path)
        if memory is None:
            return ToolResult(f"Error: The path {old_path} does not exist", is_error=True)
        if await self._file(new_path) is not None:
            return ToolResult(f"Error: The destination {new_path} already exists", is_error=True)

        metadata = dict(memory.metadata_ or {})
        metadata[PATH_KEY] = new_path
        await self._service.update(memory.public_id, title=new_path, metadata=metadata)
        return ToolResult(f"Successfully renamed {old_path} to {new_path}")

    # -- helpers --

    async def _require_file(self, path: str, *, missing: str | None = None) -> Memory:
        memory = await self._file(path)
        if memory is None:
            raise _RejectedError(
                missing or f"Error: The path {path} does not exist. Please provide a valid path."
            )
        if memory.review_status == "pending":
            raise _RejectedError(
                f"Error: The file {path} is held for human review and cannot be edited "
                "until it is approved."
            )
        return memory

    async def _store(self, path: str, text: str, *, verb: str) -> str:
        """Write a new memory-tool file through the ordinary create path.

        Which means it is scanned for secrets, checked against the trust policy,
        and may be held for review — and if it is held, Claude is told so rather
        than being left to discover next session that the file is not there.
        """
        result = await self._service.write(
            CreateMemoryInput(
                scope_type=self._scope_type,
                scope_id=self._scope_id,
                body=text,
                title=path,
                kind=MemoryKind.FACT,
                sensitivity=self._sensitivity,
                # tool_output, not manual: this was written by a model, and
                # provenance is exactly what the trust policy reads.
                source_type=MemorySource.TOOL_OUTPUT,
                source_ref={"tool": "memory_20250818", "path": path},
                metadata={PATH_KEY: path, "memory_tool": True},
            )
        )
        if result.pending_review:
            return (
                f"{verb}: {path} — but it is held for human review "
                f"({result.review_reason or 'policy'}) and will not be readable until approved."
            )
        if result.redacted:
            return f"{verb}: {path} — personal data in it was redacted before storage."
        return f"{verb}: {path}"


def _slice(body: str, window: list[Any]) -> tuple[str, int]:
    """Apply ``view_range``: ``[start, end]``, 1-indexed, ``-1`` meaning the end.

    Returns the text *and* the line it starts at, so the caller can keep the
    numbering absolute. A nonsense range falls back to the whole file rather
    than erroring — Claude asked to read something, and reading all of it is a
    more useful answer than a complaint about indices.
    """
    lines = body.split("\n")
    try:
        start = int(window[0])
        end = int(window[1])
    except (TypeError, ValueError):
        return body, 1
    start = max(1, start)
    end = len(lines) if end == -1 else min(end, len(lines))
    if start > end:
        return body, 1
    return "\n".join(lines[start - 1 : end]), start
