"""The manifests that get Kortex listed in directories.

These are files nobody runs, which is exactly why they rot: a version bump or a
rename lands everywhere the tests look and nowhere they do not, and the first
sign of trouble is a registry listing pointing at a package that moved six
months ago.

So this checks the two things that actually drift — versions and identifiers —
and the two structural rules a directory will reject the submission over.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPO_URL = "https://github.com/vedantnimbarte/kortex-memory"


def load(*parts: str) -> dict:
    return json.loads((ROOT.joinpath(*parts)).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def server() -> dict:
    return load("server.json")


@pytest.fixture(scope="module")
def plugin() -> dict:
    return load("plugin", ".claude-plugin", "plugin.json")


@pytest.fixture(scope="module")
def marketplace() -> dict:
    return load(".claude-plugin", "marketplace.json")


# --- the things that drift --------------------------------------------------


def test_the_plugin_version_matches_the_project(plugin: dict) -> None:
    root = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert plugin["version"] == root["project"]["version"]


def test_the_registry_version_matches_the_project(server: dict) -> None:
    root = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert server["version"] == root["project"]["version"]


@pytest.mark.parametrize("fixture", ["server", "plugin"])
def test_every_manifest_points_at_this_repository(fixture: str, request) -> None:  # type: ignore[no-untyped-def]
    doc = request.getfixturevalue(fixture)
    urls = json.dumps(doc)
    assert REPO_URL in urls, f"{fixture} does not reference {REPO_URL}"


def test_the_marketplace_points_at_a_plugin_that_exists(marketplace: dict) -> None:
    """A source path that does not resolve fails at install time, in front of
    the user, with a message that does not say which file is wrong."""
    for entry in marketplace["plugins"]:
        source = ROOT / entry["source"]
        assert (source / ".claude-plugin" / "plugin.json").is_file(), source


def test_the_marketplace_and_plugin_agree_on_the_name(marketplace: dict, plugin: dict) -> None:
    """`/plugin install <name>@<marketplace>` uses the marketplace's name; the
    plugin's own name is what appears everywhere afterwards. A mismatch installs
    something the user cannot then find."""
    assert [p["name"] for p in marketplace["plugins"]] == [plugin["name"]]


# --- rules a directory will reject the submission over ----------------------


def test_the_registry_name_uses_the_verifiable_github_namespace(server: dict) -> None:
    """The official registry proves namespace ownership. `io.github.<user>/*`
    is verified through GitHub OAuth; a domain namespace would need DNS control
    we have not set up."""
    assert server["name"] == "io.github.vedantnimbarte/kortex-memory"


def test_the_registry_manifest_offers_a_way_to_actually_run_it(server: dict) -> None:
    """A server.json with neither packages nor remotes validates and is useless."""
    assert server.get("packages") or server.get("remotes")


def test_registry_packages_come_from_registries_the_index_allows(server: dict) -> None:
    """Private registries and mirrors are rejected. GHCR is on the allowed list;
    a package from anywhere else fails verification with a 404 that does not
    explain itself."""
    allowed = {"npm", "pypi", "oci", "nuget", "cargo", "mcpb"}
    for package in server.get("packages", []):
        assert package["registryType"] in allowed


def test_secrets_in_the_registry_manifest_are_marked_secret(server: dict) -> None:
    """A directory renders these in its UI. An API key or a database DSN not
    flagged `isSecret` gets shown in plain text on a public page."""
    for package in server.get("packages", []):
        for var in package.get("environmentVariables", []):
            if "KEY" in var["name"] or "URL" in var["name"]:
                assert var.get("isSecret") is True, var["name"]


# --- the plugin --------------------------------------------------------------


def test_the_plugin_asks_for_a_key_without_storing_it_in_settings(plugin: dict) -> None:
    """`sensitive` sends the value to the system keychain instead of
    settings.json, which people commit."""
    assert plugin["userConfig"]["api_key"]["sensitive"] is True


def test_the_plugin_mcp_config_consumes_the_values_it_asks_for(plugin: dict) -> None:
    """Prompting for config nothing reads is a question the user answers for no
    reason, and the server then fails with a blank credential."""
    mcp = json.loads((ROOT / "plugin" / plugin["mcpServers"]).read_text(encoding="utf-8"))
    rendered = json.dumps(mcp)
    for key in plugin["userConfig"]:
        assert f"${{user_config.{key}}}" in rendered, key


def test_the_bundled_skill_is_where_the_plugin_says(plugin: dict) -> None:
    skills = ROOT / "plugin" / plugin["skills"]
    assert list(skills.glob("*/SKILL.md")), f"no skills under {skills}"


def test_every_harness_the_cli_supports_has_a_guide() -> None:
    """`kortex init` advertising a harness with no guide behind it is the gap
    people hit right after the command works."""
    from kortex_cli.harnesses import HARNESSES

    documented = {p.stem for p in (ROOT / "docs" / "integrations").glob("*.md")}
    assert set(HARNESSES) <= documented
