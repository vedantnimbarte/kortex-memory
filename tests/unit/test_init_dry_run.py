"""What ``kortex init`` must not do: mutate on a dry run, verify as the wrong key.

Both bugs were invisible from the outside. The dry run printed "nothing
written" while having already created a project and minted a live credential,
and verification failed on a correctly wired install because it authenticated
as the profile rather than as the key it had just installed.
"""

from __future__ import annotations

from pathlib import Path

from kortex_cli.cmds import init as init_mod
from kortex_cli.config import CliProfile


class _ReadOnlyClient:
    """Answers reads; fails the test on any write."""

    def __init__(self, projects: list[dict]) -> None:
        self._projects = projects

    def get(self, path: str) -> object:
        if path == "/v1/workspaces":
            return [{"public_id": "ws-1", "slug": "default"}]
        if path.endswith("/projects"):
            return self._projects
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, json: dict | None = None) -> dict:
        raise AssertionError(f"a dry run wrote to {path}")


def test_dry_run_does_not_create_a_missing_project(tmp_path: Path) -> None:
    project = init_mod._resolve_project(
        _ReadOnlyClient([]),  # type: ignore[arg-type]
        None,
        tmp_path,
        create=False,
    )

    assert project["id"] == 0
    assert project["slug"] == init_mod._slugify(tmp_path.name)


def test_dry_run_still_reports_a_project_that_already_exists(tmp_path: Path) -> None:
    existing = {"id": 7, "slug": init_mod._slugify(tmp_path.name), "public_id": "p-7"}

    project = init_mod._resolve_project(
        _ReadOnlyClient([existing]),  # type: ignore[arg-type]
        None,
        tmp_path,
        create=False,
    )

    assert project == existing


def test_dry_run_does_not_mint_a_key() -> None:
    key = init_mod._resolve_key(
        _ReadOnlyClient([]),  # type: ignore[arg-type]
        {"id": 1, "slug": "repo"},
        "kx_profile",
        mint=False,
    )

    assert key == "kx_profile"


def test_verification_authenticates_as_the_installed_key(monkeypatch) -> None:
    """The profile key holds no role in a project it is not bound to."""
    seen: dict[str, str | None] = {}

    class _FakeClient:
        def __init__(self, profile: CliProfile) -> None:
            seen["api_key"] = profile.api_key

        def __enter__(self) -> _FakeClient:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def post(self, path: str, json: dict | None = None) -> dict:
            return {"public_id": "canary-1"}

        def get(self, path: str) -> dict:
            return {}

        def delete(self, path: str) -> None:
            return None

    monkeypatch.setattr(init_mod, "ApiClient", _FakeClient)

    init_mod._verify(
        CliProfile(name="default", api_url="http://localhost:8000", api_key="kx_profile"),
        "kx_minted",
        {"id": 2, "slug": "repo"},
    )

    assert seen["api_key"] == "kx_minted"
