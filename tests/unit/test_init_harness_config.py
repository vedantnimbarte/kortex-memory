"""Harness-config merging for ``kortex init``.

The three properties that matter, checked for every harness: we never drop a
key we did not add, we never write over a file we could not parse, and merging
twice is byte-identical (so re-running `kortex init` is a no-op).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomlkit
from kortex_cli.harnesses import (
    HARNESSES,
    SERVER_NAME,
    HarnessError,
    McpServer,
    merge_session_start_hook,
    write_merged,
)

SERVER = McpServer(
    url="http://localhost:8765/sse",
    api_key="kx_test_key",
    env={"KORTEX_API_KEY": "kx_test_key", "KORTEX_DATABASE_URL": "postgresql+asyncpg://x/y"},
)

ALL = list(HARNESSES.values())
JSON_HARNESSES = [h for h in ALL if h.key != "codex"]
REMOTE_HARNESSES = [h for h in ALL if h.remote_ok]


def _entry(harness_key: str, text: str) -> dict:
    """Pull the kortex entry back out, whatever container the harness uses."""
    if harness_key == "codex":
        return dict(tomlkit.parse(text)["mcp_servers"][SERVER_NAME])
    doc = json.loads(text)
    container = "mcp" if harness_key == "opencode" else "mcpServers"
    return doc[container][SERVER_NAME]


# --- the entry itself --------------------------------------------------------


@pytest.mark.parametrize("harness", ALL, ids=lambda h: h.key)
def test_creates_entry_from_nothing(harness) -> None:
    text = harness.merge(None, Path("cfg"), SERVER, harness.remote_ok)
    assert _entry(harness.key, text)


@pytest.mark.parametrize("harness", REMOTE_HARNESSES, ids=lambda h: h.key)
def test_remote_entry_carries_url_and_bearer(harness) -> None:
    entry = _entry(harness.key, harness.merge(None, Path("cfg"), SERVER, True))
    assert entry["url"] == SERVER.url
    assert entry["headers"]["Authorization"] == "Bearer kx_test_key"


@pytest.mark.parametrize("harness", ALL, ids=lambda h: h.key)
def test_stdio_entry_carries_command_and_env(harness) -> None:
    entry = _entry(harness.key, harness.merge(None, Path("cfg"), SERVER, False))
    is_opencode = harness.key == "opencode"
    expected_command = ["kortex-mcp", "stdio"] if is_opencode else "kortex-mcp"
    assert entry["command"] == expected_command
    env = entry["environment"] if is_opencode else entry["env"]
    assert env["KORTEX_API_KEY"] == "kx_test_key"
    assert env["KORTEX_DATABASE_URL"] == "postgresql+asyncpg://x/y"


def test_codex_ignores_remote_and_still_writes_stdio() -> None:
    """Codex has no remote-MCP form; asking for one must not produce a broken entry."""
    entry = _entry("codex", HARNESSES["codex"].merge(None, Path("cfg"), SERVER, True))
    assert entry["command"] == "kortex-mcp"
    assert "url" not in entry


# --- not clobbering ----------------------------------------------------------


@pytest.mark.parametrize("harness", JSON_HARNESSES, ids=lambda h: h.key)
def test_preserves_unrelated_servers_and_keys(harness) -> None:
    container = "mcp" if harness.key == "opencode" else "mcpServers"
    existing = json.dumps(
        {
            "someOtherTopLevelKey": {"keep": "me"},
            container: {"github": {"command": "gh-mcp", "args": []}},
        }
    )
    doc = json.loads(harness.merge(existing, Path("cfg"), SERVER, harness.remote_ok))
    assert doc["someOtherTopLevelKey"] == {"keep": "me"}
    assert doc[container]["github"] == {"command": "gh-mcp", "args": []}
    assert SERVER_NAME in doc[container]


def test_codex_preserves_other_servers_and_comments() -> None:
    existing = '# hand-written\n[mcp_servers.github]\ncommand = "gh-mcp"\n'
    text = HARNESSES["codex"].merge(existing, Path("cfg"), SERVER, False)
    assert "# hand-written" in text
    assert tomlkit.parse(text)["mcp_servers"]["github"]["command"] == "gh-mcp"


@pytest.mark.parametrize("harness", ALL, ids=lambda h: h.key)
def test_upgrades_existing_kortex_entry_in_place(harness) -> None:
    first = harness.merge(None, Path("cfg"), SERVER, harness.remote_ok)
    rotated = McpServer(url=SERVER.url, api_key="kx_rotated", env={"KORTEX_API_KEY": "kx_rotated"})
    entry = _entry(harness.key, harness.merge(first, Path("cfg"), rotated, harness.remote_ok))
    assert "kx_test_key" not in json.dumps(entry, default=str)


@pytest.mark.parametrize("harness", JSON_HARNESSES, ids=lambda h: h.key)
def test_malformed_json_raises_and_never_returns_text(harness) -> None:
    with pytest.raises(HarnessError):
        harness.merge("{ not json at all", Path("cfg"), SERVER, harness.remote_ok)


@pytest.mark.parametrize("harness", JSON_HARNESSES, ids=lambda h: h.key)
def test_wrong_container_type_raises(harness) -> None:
    container = "mcp" if harness.key == "opencode" else "mcpServers"
    with pytest.raises(HarnessError):
        harness.merge(json.dumps({container: "a string"}), Path("cfg"), SERVER, harness.remote_ok)


# --- idempotency -------------------------------------------------------------


@pytest.mark.parametrize("harness", ALL, ids=lambda h: h.key)
@pytest.mark.parametrize("remote", [True, False])
def test_merge_is_byte_stable(harness, remote: bool) -> None:
    once = harness.merge(None, Path("cfg"), SERVER, remote)
    twice = harness.merge(once, Path("cfg"), SERVER, remote)
    assert once == twice


# --- hooks -------------------------------------------------------------------


def test_hook_installed_once_and_not_duplicated() -> None:
    once = merge_session_start_hook(None, Path("settings.json"))
    twice = merge_session_start_hook(once, Path("settings.json"))
    assert once == twice
    groups = json.loads(twice)["hooks"]["SessionStart"]
    assert sum(len(g["hooks"]) for g in groups) == 1


def test_hook_preserves_existing_hooks() -> None:
    existing = json.dumps(
        {
            "permissions": {"allow": ["Bash"]},
            "hooks": {
                "SessionStart": [{"hooks": [{"type": "command", "command": "other-tool"}]}],
                "PreToolUse": [{"hooks": [{"type": "command", "command": "linter"}]}],
            },
        }
    )
    doc = json.loads(merge_session_start_hook(existing, Path("settings.json")))
    assert doc["permissions"] == {"allow": ["Bash"]}
    assert doc["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "linter"
    commands = [h["command"] for g in doc["hooks"]["SessionStart"] for h in g["hooks"]]
    assert commands == ["other-tool", "kortex hook session-start"]


def test_hook_rejects_wrong_shape() -> None:
    with pytest.raises(HarnessError):
        merge_session_start_hook(json.dumps({"hooks": {"SessionStart": "nope"}}), Path("s.json"))


# --- writing -----------------------------------------------------------------


def test_write_reports_created_updated_unchanged_and_backs_up(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "cfg.json"
    assert write_merged(path, "one\n") == "created"
    assert write_merged(path, "one\n") == "unchanged"
    assert write_merged(path, "two\n") == "updated"
    assert path.read_text(encoding="utf-8") == "two\n"
    assert (tmp_path / "nested" / "cfg.json.bak").read_text(encoding="utf-8") == "one\n"
