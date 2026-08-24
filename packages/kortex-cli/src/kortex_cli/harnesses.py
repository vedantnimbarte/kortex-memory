"""Where each agent harness keeps its MCP config, and how to merge Kortex into it.

One table, four harnesses. Every merge is a read-modify-write on the *parsed*
document, which buys three properties `kortex init` depends on:

* **Never clobber** — keys we did not add survive untouched; an unparseable
  file raises :class:`HarnessError` instead of being overwritten.
* **Idempotent** — merging twice yields byte-identical output, so re-running
  ``kortex init`` is a no-op rather than a duplicate entry.
* **Upgradable** — an existing ``kortex`` entry is replaced in place.

JSON files are re-serialised with two-space indent, so the first merge may
reformat a hand-indented file. TOML goes through ``tomlkit``, which preserves
comments and layout.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import tomlkit

SERVER_NAME = "kortex"
HOOK_COMMAND = "kortex hook session-start"


class HarnessError(Exception):
    """Raised when a harness config exists but cannot be safely updated."""


@dataclass(frozen=True, slots=True)
class McpServer:
    """How to reach the Kortex MCP server, described in both transports.

    Both are always populated so a harness that cannot speak SSE (Codex) can
    still be wired up from the same resolution pass.
    """

    url: str
    api_key: str
    command: str = "kortex-mcp"
    args: tuple[str, ...] = ("stdio",)
    env: dict[str, str] = field(default_factory=dict)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}


# --- serialisation helpers ---------------------------------------------------


def _load_json(text: str | None, path: Path) -> dict:
    if not text or not text.strip():
        return {}
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise HarnessError(f"{path} is not valid JSON ({e}) — refusing to overwrite it") from e
    if not isinstance(doc, dict):
        raise HarnessError(f"{path} is not a JSON object — refusing to overwrite it")
    return doc


def _dump_json(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _table(doc: dict, key: str, path: Path) -> dict:
    """Fetch ``doc[key]`` as a dict, creating it when absent.

    Refuses to proceed when the key exists but holds something else — that is a
    config we do not understand, and guessing would destroy it.
    """
    existing = doc.get(key)
    if existing is None:
        new: dict = {}
        doc[key] = new
        return new
    if not isinstance(existing, dict):
        raise HarnessError(
            f"{path}: expected `{key}` to be an object, found {type(existing).__name__}"
        )
    return existing


# --- per-harness entry shapes ------------------------------------------------


def _mcp_servers_entry(server: McpServer, remote: bool) -> dict:
    """The `mcpServers` shape shared by Claude Code and Cursor."""
    if remote:
        return {"type": "sse", "url": server.url, "headers": server.headers}
    return {"command": server.command, "args": list(server.args), "env": dict(server.env)}


def _merge_mcp_servers(text: str | None, path: Path, server: McpServer, remote: bool) -> str:
    doc = _load_json(text, path)
    _table(doc, "mcpServers", path)[SERVER_NAME] = _mcp_servers_entry(server, remote)
    return _dump_json(doc)


def _merge_opencode(text: str | None, path: Path, server: McpServer, remote: bool) -> str:
    doc = _load_json(text, path)
    doc.setdefault("$schema", "https://opencode.ai/config.json")
    entry = (
        {"type": "remote", "url": server.url, "headers": server.headers, "enabled": True}
        if remote
        else {
            "type": "local",
            "command": [server.command, *server.args],
            "environment": dict(server.env),
            "enabled": True,
        }
    )
    _table(doc, "mcp", path)[SERVER_NAME] = entry
    return _dump_json(doc)


def _merge_codex(text: str | None, _path: Path, server: McpServer, _remote: bool) -> str:
    """Codex keeps TOML and speaks stdio only, so `remote` is ignored here."""
    doc = tomlkit.parse(text) if text and text.strip() else tomlkit.document()
    servers = doc.get("mcp_servers")
    if servers is None:
        servers = tomlkit.table(is_super_table=True)
        doc["mcp_servers"] = servers
    entry = tomlkit.table()
    entry["command"] = server.command
    entry["args"] = list(server.args)
    env = tomlkit.inline_table()
    env.update(server.env)
    entry["env"] = env
    servers[SERVER_NAME] = entry
    return tomlkit.dumps(doc)


# --- the table ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Harness:
    key: str
    label: str
    remote_ok: bool
    """False when the harness has no remote-MCP form and must be given stdio."""
    project_scoped: bool
    """False when the harness only has a single user-level config file."""
    path: Callable[[Path], Path]
    merge: Callable[[str | None, Path, McpServer, bool], str]


HARNESSES: dict[str, Harness] = {
    "claude-code": Harness(
        key="claude-code",
        label="Claude Code",
        remote_ok=True,
        project_scoped=True,
        path=lambda root: root / ".mcp.json",
        merge=_merge_mcp_servers,
    ),
    "cursor": Harness(
        key="cursor",
        label="Cursor",
        remote_ok=True,
        project_scoped=True,
        path=lambda root: root / ".cursor" / "mcp.json",
        merge=_merge_mcp_servers,
    ),
    "opencode": Harness(
        key="opencode",
        label="OpenCode",
        remote_ok=True,
        project_scoped=True,
        path=lambda root: root / "opencode.json",
        merge=_merge_opencode,
    ),
    "codex": Harness(
        key="codex",
        label="Codex",
        remote_ok=False,
        project_scoped=False,
        path=lambda _root: Path.home() / ".codex" / "config.toml",
        merge=_merge_codex,
    ),
}


def global_path(harness: Harness) -> Path:
    """The user-level config for harnesses that also support a project-local one."""
    if harness.key == "claude-code":
        return Path.home() / ".claude.json"
    if harness.key == "cursor":
        return Path.home() / ".cursor" / "mcp.json"
    if harness.key == "opencode":
        return Path.home() / ".config" / "opencode" / "opencode.json"
    return harness.path(Path.home())


# --- hooks (Claude Code) -----------------------------------------------------


def claude_settings_path(root: Path) -> Path:
    return root / ".claude" / "settings.json"


def merge_session_start_hook(text: str | None, path: Path, command: str = HOOK_COMMAND) -> str:
    """Install a SessionStart hook, unless an identical command is already there."""
    doc = _load_json(text, path)
    hooks = _table(doc, "hooks", path)
    groups = hooks.get("SessionStart")
    if groups is None:
        groups = []
        hooks["SessionStart"] = groups
    if not isinstance(groups, list):
        raise HarnessError(f"{path}: expected `hooks.SessionStart` to be a list")
    for group in groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks", []):
            if isinstance(hook, dict) and hook.get("command") == command:
                return _dump_json(doc)  # already installed — leave it alone
    groups.append({"hooks": [{"type": "command", "command": command}]})
    return _dump_json(doc)


# --- writing -----------------------------------------------------------------


def write_merged(path: Path, new_text: str) -> str:
    """Write ``new_text`` to ``path``, backing up any file we are replacing.

    Returns one of ``created`` / ``updated`` / ``unchanged`` for reporting.
    """
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == new_text:
            return "unchanged"
        path.with_suffix(path.suffix + ".bak").write_text(current, encoding="utf-8")
        path.write_text(new_text, encoding="utf-8")
        return "updated"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding="utf-8")
    return "created"


def read_text_if_exists(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None
